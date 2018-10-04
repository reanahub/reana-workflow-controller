# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller MQ Consumer."""

import json

import pika
from reana_commons.consumer import BaseConsumer
from reana_db.database import Session
from reana_db.models import WorkflowStatus

from .config import STATUS_QUEUE
from .tasks import (_update_job_cache, _update_job_progress,
                    _update_run_progress, _update_workflow_status)


class JobStatusConsumer(BaseConsumer):
    """Consumer of jobs-status queue."""

    def __init__(self):
        """Constructor."""
        super(JobStatusConsumer, self).__init__()

    def get_consumers(self, Consumer, channel):
        """Implement providing kombu.Consumers with queues/callbacks."""
        return [Consumer(queues=self.queues, callbacks=[self.on_message],
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
