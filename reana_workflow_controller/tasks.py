# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017 CERN.
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

"""Celery tasks definition."""

from __future__ import absolute_import

import json

import pika
from celery import Celery
from reana_commons.database import Session
from reana_commons.models import Job, Run, Workflow, WorkflowStatus

from reana_workflow_controller.config import (BROKER, BROKER_PASS, BROKER_PORT,
                                              BROKER_URL, BROKER_USER)

celery = Celery('tasks',
                broker=BROKER)

celery.conf.update(CELERY_ACCEPT_CONTENT=['json'],
                   CELERY_TASK_SERIALIZER='json')


run_yadage_workflow = celery.signature('tasks.run_yadage_workflow')
run_cwl_workflow = celery.signature('tasks.run_cwl_workflow')
run_serial_workflow = celery.signature('tasks.run_serial_workflow')


def consume_job_queue():
    """Consumes job queue and updates job status."""
    def _callback_job_status(ch, method, properties, body):
        body_dict = json.loads(body)
        workflow_uuid = body_dict.get('workflow_uuid')
        if workflow_uuid:
            status = WorkflowStatus(body_dict.get('status'))
            print(" [x] Received workflow_uuid:{0} status: {1}".
                  format(workflow_uuid, status))
            logs = body_dict.get('logs') or ''
            Workflow.update_workflow_status(Session, workflow_uuid,
                                            status, logs, None)
            if 'message' in body_dict and body_dict.get('message'):
                msg = body_dict['message']
                if 'job_id' in msg:
                    job_id = msg.get('job_id')
                    Session.query(Job).filter_by(
                        id_=job_id).update({'workflow_uuid': workflow_uuid})
                    del msg['job_id']
                if msg:
                    Session.query(Run).filter_by(workflow_uuid=workflow_uuid).\
                        update(msg)
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
    print(' [*] Waiting for messages. To exit press CTRL+C')
    channel.start_consuming()
