# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# REANA is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# REANA; if not, write to the Free Software Foundation, Inc., 59 Temple Place,
# Suite 330, Boston, MA 02111-1307, USA.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization or
# submit itself to any jurisdiction.

"""REANA Workflow Controller command line interface."""

import json
import logging

import click
import pika
from reana_commons.database import Session
from reana_commons.models import WorkflowStatus

from reana_workflow_controller.config import BROKER_USER, BROKER_PASS, \
    BROKER_URL, BROKER_PORT
from reana_workflow_controller.tasks import _update_job_progress, \
    _update_run_progress, _update_workflow_status


@click.command('consume-job-queue')
def consume_job_queue():
    """Consumes job queue and updates job status."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(threadName)s - %(levelname)s: %(message)s'
    )

    def _callback_job_status(ch, method, properties, body):
        body_dict = json.loads(body)
        workflow_uuid = body_dict.get('workflow_uuid')
        if workflow_uuid:
            status = body_dict.get('status')
            if status:
                status = WorkflowStatus(status)
                print(" [x] Received workflow_uuid: {0} status: {1}".
                      format(workflow_uuid, status))
            logs = body_dict.get('logs') or ''
            _update_workflow_status(workflow_uuid, status, logs, None)
            if 'message' in body_dict and body_dict.get('message'):
                msg = body_dict['message']
                if 'progress' in msg:
                    _update_run_progress(workflow_uuid, msg)
                    _update_job_progress(workflow_uuid, msg)
                    Session.commit()

    broker_credentials = pika.credentials.PlainCredentials(BROKER_USER,
                                                           BROKER_PASS)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(BROKER_URL,
                                  BROKER_PORT,
                                  '/',
                                  broker_credentials))
    channel = connection.channel()
    channel.queue_declare(queue='jobs-status')
    channel.basic_consume(_callback_job_status,
                          queue='jobs-status',
                          no_ack=True)
    logging.info(' [*] Waiting for messages. To exit press CTRL+C')
    channel.start_consuming()
