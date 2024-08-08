# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller MQ Consumer."""

from __future__ import absolute_import

import json
import logging
import uuid
import dask.distributed as dd
from dask.distributed import Client
from datetime import datetime

import requests
from kubernetes.client.rest import ApiException
from reana_commons.config import REANA_RUNTIME_KUBERNETES_NAMESPACE
from reana_commons.consumer import BaseConsumer
from reana_commons.k8s.api_client import (
    current_k8s_batchv1_api_client,
    current_k8s_corev1_api_client,
)
from reana_commons.k8s.secrets import REANAUserSecretsStore
from reana_commons.utils import (
    calculate_file_access_time,
    calculate_hash_of_dir,
    calculate_job_input_hash,
    build_unique_component_name,
)
from reana_db.database import Session
from reana_db.models import Job, JobCache, Workflow, RunStatus
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.attributes import flag_modified

from reana_workflow_controller.config import (
    ALIVE_STATUSES,
    PROGRESS_STATUSES,
    REANA_GITLAB_URL,
    REANA_HOSTNAME,
    REANA_JOB_STATUS_CONSUMER_PREFETCH_COUNT,
)
from reana_workflow_controller.errors import REANAWorkflowControllerError

try:
    from urllib import parse as urlparse
except ImportError:
    from urlparse import urlparse


class JobStatusConsumer(BaseConsumer):
    """Consumer of jobs-status queue."""

    def __init__(self, connection=None, queue=None):
        """Initialise JobStatusConsumer class."""
        super(JobStatusConsumer, self).__init__(
            connection=connection, queue="jobs-status"
        )

    def get_consumers(self, Consumer, channel):
        """Implement providing kombu.Consumers with queues/callbacks."""
        return [
            Consumer(
                queues=self.queue,
                callbacks=[self.on_message],
                accept=[self.message_default_format],
                prefetch_count=(
                    REANA_JOB_STATUS_CONSUMER_PREFETCH_COUNT
                    if REANA_JOB_STATUS_CONSUMER_PREFETCH_COUNT
                    else None
                ),
            )
        ]

    def on_message(self, body, message):
        """Process messages on ``jobs-status`` queue for alive workflows.

        This function will ignore events about workflows that have been already
        terminated since a graceful finalisation of the workflow cannot be
        guaranteed if the workflow engine (orchestrator) is not alive.
        """
        try:
            message.ack()
            body_dict = json.loads(body)
            workflow_uuid = body_dict.get("workflow_uuid")
            workflow = (
                Session.query(Workflow)
                .filter(
                    Workflow.id_ == workflow_uuid,
                )
                .one_or_none()
            )
            if workflow and workflow.status in ALIVE_STATUSES:
                next_status = body_dict.get("status")
                if next_status:
                    next_status = RunStatus(next_status)
                    logging.info(
                        f" [x] Received workflow_uuid: {workflow_uuid} status: {next_status}"
                    )

                if workflow.can_transition_to(next_status):
                    logs = body_dict.get("logs") or ""
                    _update_workflow_status(workflow, next_status, logs)
                    if "message" in body_dict and body_dict.get("message"):
                        msg = body_dict["message"]
                        if "progress" in msg:
                            _update_run_progress(workflow_uuid, msg)
                        # Caching: calculate input hash and store in JobCache
                        if "caching_info" in msg:
                            _update_job_cache(msg)
                    Session.commit()
                else:
                    logging.error(
                        f"Cannot transition workflow {workflow.id_}"
                        f" from status {workflow.status} to"
                        f" {next_status}."
                    )
            elif workflow and workflow.status not in ALIVE_STATUSES:
                logging.warning(
                    f"Event for not alive workflow {workflow.id_} with DB status {workflow.status} received:\n"
                    f"{body}\nIgnoring..."
                )
            else:
                logging.warning(
                    f"Event for workflow {workflow_uuid} that doesn't exist in DB received:\n"
                    f"{body}\nIgnoring..."
                )
        except SQLAlchemyError as sae:
            Session.rollback()
            logging.error(
                f"Something went wrong while querying the database for workflow: {workflow_uuid}"
            )
            logging.error(sae, exc_info=True)
        except Exception as e:
            Session.rollback()
            logging.error(
                f"Unexpected error while processing workflow: {e}", exc_info=True
            )


def _update_workflow_status(workflow, status, logs):
    """Update workflow status in DB."""
    if workflow.status != status:
        Workflow.update_workflow_status(Session, workflow.id_, status, logs, None)
        if workflow.git_ref:
            _update_commit_status(workflow, status)

        if status not in ALIVE_STATUSES:
            workflow.run_finished_at = datetime.now()
            workflow.logs = workflow.logs or ""

            try:
                workflow_engine_logs = _get_workflow_engine_pod_logs(workflow)
                workflow.logs += workflow_engine_logs + "\n"
                dask_client = dd.Client("tcp://dask-scheduler.default.svc.cluster.local:8786")
                dask_log = ""
                for k, l in dask_client.get_worker_logs().items():
                    dask_log += "worker: " + k + "\n"
                    for lvl, e in l:
                        dask_log += e + "\n"
                for k, l in dask_client.get_scheduler_logs():
                    dask_log += l + "\n"
                workflow.logs += dask_log + "\n"
            except ApiException as e:
                logging.exception(
                    f"Could not fetch workflow engine pod logs for workflow {workflow.id_}. "
                    f"Error: {e}"
                )
                workflow.logs += "Workflow engine logs could not be retrieved.\n"

            if RunStatus.should_cleanup_job(status):
                try:
                    _delete_workflow_job(workflow)
                except ApiException as e:
                    logging.error(
                        f"Could not clean up workflow job for workflow {workflow.id_}. "
                        f"Error: {e}"
                    )


def _update_commit_status(workflow, status):
    if status == RunStatus.finished:
        state = "success"
    elif status == RunStatus.failed:
        state = "failed"
    elif status == RunStatus.stopped or status == RunStatus.deleted:
        state = "canceled"
    else:
        state = "running"
    secret_store = REANAUserSecretsStore(workflow.owner_id)
    gitlab_access_token = secret_store.get_secret_value("gitlab_access_token")
    target_url = f"https://{REANA_HOSTNAME}/api/workflows/{workflow.id_}/logs"
    workflow_name = urlparse.quote_plus(workflow.git_repo)
    system_name = "reana"
    commit_status_url = (
        f"{REANA_GITLAB_URL}/api/v4/projects/{workflow_name}/statuses/"
        f"{workflow.git_ref}?access_token={gitlab_access_token}&state={state}&"
        f"target_url={target_url}&name={system_name}"
    )
    requests.post(commit_status_url)


def _update_run_progress(workflow_uuid, msg):
    """Register succeeded Jobs to DB."""
    workflow = Session.query(Workflow).filter_by(id_=workflow_uuid).one_or_none()
    cached_jobs = None
    job_progress = workflow.job_progress
    if "cached" in msg["progress"]:
        cached_jobs = msg["progress"]["cached"]  # noqa: F841
    for status, _ in PROGRESS_STATUSES:
        if status in msg["progress"]:
            previous_status = workflow.job_progress.get(status)
            previous_total = 0
            if previous_status:
                previous_total = previous_status.get("total") or 0
            if status == "total":
                if previous_total > 0:
                    continue
                else:
                    job_progress["total"] = msg["progress"]["total"]
            else:
                # remove invalid job IDs like `None`
                new_job_ids = {
                    job_id for job_id in msg["progress"][status]["job_ids"] if job_id
                }
                if previous_status:
                    new_job_ids |= set(previous_status.get("job_ids") or set())
                job_progress[status] = {
                    "total": len(new_job_ids),
                    "job_ids": list(new_job_ids),
                }
    workflow.job_progress = job_progress
    flag_modified(workflow, "job_progress")
    Session.add(workflow)


def _update_job_cache(msg):
    """Update caching information for finished job."""
    cached_job = (
        Session.query(JobCache)
        .filter_by(job_id=msg["caching_info"].get("job_id"))
        .first()
    )

    input_files = []
    if cached_job:
        file_access_times = calculate_file_access_time(
            msg["caching_info"].get("workflow_workspace")
        )
        for filename in cached_job.access_times:
            if filename in file_access_times:
                input_files.append(filename)
    else:
        return
    cmd = msg["caching_info"]["job_spec"]["cmd"]
    # removes cd to workspace, to be refactored
    clean_cmd = ";".join(cmd.split(";")[1:])
    msg["caching_info"]["job_spec"]["cmd"] = clean_cmd

    if "workflow_workspace" in msg["caching_info"]["job_spec"]:
        del msg["caching_info"]["job_spec"]["workflow_workspace"]
    input_hash = calculate_job_input_hash(
        msg["caching_info"]["job_spec"], msg["caching_info"]["workflow_json"]
    )
    workspace_hash = calculate_hash_of_dir(
        msg["caching_info"].get("workflow_workspace"), input_files
    )
    if workspace_hash == -1:
        return

    cached_job.parameters = input_hash
    cached_job.result_path = msg["caching_info"].get("result_path")
    cached_job.workspace_hash = workspace_hash
    Session.add(cached_job)


def _delete_workflow_job(workflow: Workflow) -> None:
    job_name = build_unique_component_name("run-batch", workflow.id_)
    current_k8s_batchv1_api_client.delete_namespaced_job(
        name=job_name,
        namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
        propagation_policy="Background",
    )


def _get_workflow_engine_pod_logs(workflow: Workflow) -> str:
    pods = current_k8s_corev1_api_client.list_namespaced_pod(
        namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
        label_selector=f"reana-run-batch-workflow-uuid={str(workflow.id_)}",
    )
    for pod in pods.items:
        if str(workflow.id_) in pod.metadata.name:
            return current_k8s_corev1_api_client.read_namespaced_pod_log(
                namespace=pod.metadata.namespace,
                name=pod.metadata.name,
                container="workflow-engine",
            )
    # There might not be any pod returned by `list_namespaced_pod`, for example
    # when a workflow fails to be scheduled
    return ""
