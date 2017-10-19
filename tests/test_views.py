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
"""REANA-Workflow-Controller fsdb module tests."""

from __future__ import absolute_import, print_function

import json
import uuid

from flask import url_for

from reana_workflow_controller.models import User, Workflow, WorkflowStatus


def test_get_workflows(app, default_user, db_session):
    """Test listing all workflows."""
    with app.test_client() as client:
        workflow_uuid = uuid.uuid4()
        workflow = Workflow(id_=workflow_uuid,
                            workspace_path='',
                            status=WorkflowStatus.finished,
                            owner_id=default_user.id_)
        db_session.add(workflow)
        db_session.commit()
        res = client.get(url_for('api.get_workflows'),
                         query_string={
                             "user": default_user.id_,
                             "organization": 'default'})
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))
        expected_data = [
            {
                "id": str(workflow.id_),
                "organization": "default",
                "status": workflow.status.name,
                "user": str(workflow.owner_id)
            }
        ]

        assert response_data == expected_data
