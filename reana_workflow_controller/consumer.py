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

"""REANA Workflow Controller MQ Consumer."""

import json

import pika
from reana_commons.consumer import Consumer
from reana_db.database import Session
from reana_db.models import WorkflowStatus

from .config import STATUS_QUEUE
from .tasks import (_update_job_cache, _update_job_progress,
                    _update_run_progress, _update_workflow_status)


class JobStatusConsumer(Consumer):
    """Consumer of jobs-status queue."""

    def __init__(self):
        """Constructor."""
        super(JobStatusConsumer, self).__init__(STATUS_QUEUE)

    def on_message(self, channel, method_frame, header_frame, body):
        """On new message event handler."""
        self._channel.basic_ack(delivery_tag=method_frame.delivery_tag)
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

    def consume(self):
        """Start consuming incoming messages."""
        while True:
            self.connect()
            self._channel.basic_consume(self.on_message, STATUS_QUEUE)
            try:
                self._channel.start_consuming()
            except KeyboardInterrupt:
                self._channel.stop_consuming()
                self._conn.close()
            except pika.exceptions.ConnectionClosed:
                # Uncomment this to make the example not attempt recovery
                # from server-initiated connection closure, including
                # when the node is stopped cleanly
                # except pika.exceptions.ConnectionClosedByBroker:
                #     pass
                continue
