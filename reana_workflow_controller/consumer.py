# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller MQ Consumer."""

from __future__ import absolute_import

import json
import uuid
from datetime import datetime

import requests
from kubernetes.client.rest import ApiException
from reana_commons.consumer import BaseConsumer
from reana_commons.k8s.api_client import current_k8s_batchv1_api_client
from reana_commons.k8s.secrets import REANAUserSecretsStore
from reana_commons.utils import (calculate_file_access_time,
                                 calculate_hash_of_dir,
                                 calculate_job_input_hash)
from reana_db.database import Session
from reana_db.models import Job, JobCache, Workflow, WorkflowStatus
from sqlalchemy.orm.attributes import flag_modified

from reana_workflow_controller.config import (PROGRESS_STATUSES,
                                              REANA_GITLAB_URL, REANA_URL)
from reana_workflow_controller.errors import REANAWorkflowControllerError

try:
    from urllib import parse as urlparse
except ImportError:
    from urlparse import urlparse


class JobStatusConsumer(BaseConsumer):
    """Consumer of jobs-status queue."""

    def __init__(self):
        """Initialise JobStatusConsumer class."""
        super(JobStatusConsumer, self).__init__(queue='jobs-status')

    def get_consumers(self, Consumer, channel):
        """Implement providing kombu.Consumers with queues/callbacks."""
        return [Consumer(queues=self.queue, callbacks=[self.on_message],
                         accept=[self.message_default_format])]

    def on_message(self, body, message):
        """On new message event handler."""
        message.ack()
        body_dict = json.loads(body)
        workflow_uuid = body_dict.get('workflow_uuid')
        if workflow_uuid:
            status = body_dict.get('status')
            if status:
                status = WorkflowStatus(status)
                print(" [x] Received workflow_uuid: {0} status: {1}".
                      format(workflow_uuid, status))
            logs = body_dict.get('logs') or ''
            _update_workflow_status(workflow_uuid, status, logs)
            if 'message' in body_dict and body_dict.get('message'):
                msg = body_dict['message']
                if 'progress' in msg:
                    _update_run_progress(workflow_uuid, msg)
                    _update_job_progress(workflow_uuid, msg)
                # Caching: calculate input hash and store in JobCache
                if 'caching_info' in msg:
                    _update_job_cache(msg)
                Session.commit()


def _update_workflow_status(workflow_uuid, status, logs):
    """Update workflow status in DB."""
    Workflow.update_workflow_status(Session, workflow_uuid,
                                    status, logs, None)
    workflow = Session.query(Workflow).filter_by(id_=workflow_uuid)\
        .one_or_none()
    if workflow.git_ref:
        _update_commit_status(workflow, status)
    alive_statuses = \
        [WorkflowStatus.created, WorkflowStatus.running, WorkflowStatus.queued]
    if status not in alive_statuses:
        if not workflow.restart:
            workflow.run_finished_at = datetime.now()
        else:
            workflow.restart_info[-1]['restart_finished_at'] = \
                str(datetime.now())
            flag_modified(workflow, 'restart_info')
            Session.add(workflow)
        _delete_workflow_engine_pod(workflow_uuid)


def _update_commit_status(workflow, status):
    if status == WorkflowStatus.finished:
        state = "success"
    elif status == WorkflowStatus.failed:
        state = "failed"
    elif status == WorkflowStatus.stopped or status == WorkflowStatus.deleted:
        state = "canceled"
    else:
        state = "running"
    secret_store = REANAUserSecretsStore(workflow.owner_id)
    gitlab_access_token = secret_store.get_secret_value('gitlab_access_token')
    target_url = f"https://{REANA_URL}/api/workflows/{workflow.id_}/logs"
    workflow_name = urlparse.quote_plus(workflow.git_repo)
    commit_status_url = (
        f"{REANA_GITLAB_URL}/api/v4/projects/{workflow_name}/statuses/"
        f"{workflow.git_ref}?access_token={gitlab_access_token}&state={state}&"
        f"target_url={target_url}"
    )
    requests.post(commit_status_url)


def _update_run_progress(workflow_uuid, msg):
    """Register succeeded Jobs to DB."""
    workflow = Session.query(Workflow).filter_by(id_=workflow_uuid).\
        one_or_none()
    cached_jobs = None
    job_progress = workflow.job_progress
    if "cached" in msg['progress']:
        cached_jobs = msg['progress']['cached']
    for status in PROGRESS_STATUSES:
        if status in msg['progress']:
            previous_status = workflow.job_progress.get(status)
            previous_total = 0
            if previous_status:
                previous_total = previous_status.get('total') or 0
            if status == 'total':
                if previous_total > 0:
                    continue
                else:
                    job_progress['total'] = \
                        msg['progress']['total']
            else:
                if previous_status:
                    new_job_ids = set(previous_status.get('job_ids') or
                                      set()) | \
                        set(msg['progress'][status]['job_ids'])
                else:
                    new_job_ids = set(msg['progress'][status]['job_ids'])
                job_progress[status] = {'total': len(new_job_ids),
                                        'job_ids': list(new_job_ids)}
    workflow.job_progress = job_progress
    flag_modified(workflow, 'job_progress')
    Session.add(workflow)


def _update_job_progress(workflow_uuid, msg):
    """Update job progress for jobs in received message."""
    for status in PROGRESS_STATUSES:
        if status in msg['progress']:
            status_progress = msg['progress'][status]
            for job_id in status_progress['job_ids']:
                try:
                    uuid.UUID(job_id)
                except Exception:
                    continue
                Session.query(Job).filter_by(id_=job_id).\
                    update({'workflow_uuid': workflow_uuid,
                            'status': status})


def _update_job_cache(msg):
    """Update caching information for finished job."""
    cached_job = Session.query(JobCache).filter_by(
        job_id=msg['caching_info'].get('job_id')).first()

    input_files = []
    if cached_job:
        file_access_times = calculate_file_access_time(
            msg['caching_info'].get('workflow_workspace'))
        for filename in cached_job.access_times:
            if filename in file_access_times:
                input_files.append(filename)
    else:
        return
    cmd = msg['caching_info']['job_spec']['cmd']
    # removes cd to workspace, to be refactored
    clean_cmd = ';'.join(cmd.split(';')[1:])
    msg['caching_info']['job_spec']['cmd'] = clean_cmd

    if 'workflow_workspace' in msg['caching_info']['job_spec']:
        del msg['caching_info']['job_spec']['workflow_workspace']
    input_hash = calculate_job_input_hash(msg['caching_info']['job_spec'],
                                          msg['caching_info']['workflow_json'])
    workspace_hash = calculate_hash_of_dir(
        msg['caching_info'].get('workflow_workspace'), input_files)
    if workspace_hash == -1:
        return

    cached_job.parameters = input_hash
    cached_job.result_path = msg['caching_info'].get('result_path')
    cached_job.workspace_hash = workspace_hash
    Session.add(cached_job)


def _delete_workflow_engine_pod(workflow_uuid):
    """Delete workflow engine pod."""
    try:
        jobs = current_k8s_batchv1_api_client.list_namespaced_job(
            namespace='default',
        )
        for job in jobs.items:
            if workflow_uuid in job.metadata.name:
                current_k8s_batchv1_api_client.delete_namespaced_job(
                    namespace='default',
                    propagation_policy="Background",
                    name=job.metadata.name)
                break
    except ApiException as e:
        raise REANAWorkflowControllerError(
            "Workflow engine pod cound not be deleted {}.".format(e))
