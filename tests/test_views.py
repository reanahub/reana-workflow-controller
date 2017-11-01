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
import os
import uuid

from flask import url_for
from werkzeug.utils import secure_filename

from reana_workflow_controller.fsdb import get_user_analyses_dir
from reana_workflow_controller.models import Workflow, WorkflowStatus


def test_get_workflows(app, default_user, db_session):
    """Test listing all workflows."""
    with app.test_client() as client:
        workflow_uuid = uuid.uuid4()
        data = {'parameters': {'min_year': '1991',
                               'max_year': '2001'},
                'specification': {'first': 'do this',
                                  'second': 'do that'},
                'type': 'cwl'}
        workflow = Workflow(id_=workflow_uuid,
                            workspace_path='',
                            status=WorkflowStatus.finished,
                            owner_id=default_user.id_,
                            specification=data['specification'],
                            parameters=data['parameters'],
                            type_=data['type'])
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


def test_get_workflows_wrong_user(app):
    """Test list of workflows for unknown user."""
    with app.test_client() as client:
        random_user_uuid = uuid.uuid4()
        res = client.get(url_for('api.get_workflows'),
                         query_string={
                             "user": random_user_uuid,
                             "organization": 'default'})
        assert res.status_code == 404


def test_get_workflows_missing_user(app):
    """Test listing all workflows with missing user."""
    with app.test_client() as client:
        res = client.get(url_for('api.get_workflows'),
                         query_string={"organization": 'default'})
        assert res.status_code == 400


def test_get_workflows_wrong_organization(app, default_user):
    """Test list of workflows for unknown organization."""
    with app.test_client() as client:
        organization = 'wrong_organization'
        res = client.get(url_for('api.get_workflows'),
                         query_string={
                             "user": default_user.id_,
                             "organization": organization})
        assert res.status_code == 404


def test_get_workflows_missing_organization(app, default_user):
    """Test listing all workflows with missing organization."""
    with app.test_client() as client:
        res = client.get(url_for('api.get_workflows'),
                         query_string={"user": default_user.id_})
        assert res.status_code == 400


def test_create_workflow(app, default_user, db_session,
                         tmp_shared_volume_path):
    """Test create workflow and its workspace."""
    with app.test_client() as client:
        organization = 'default'
        data = {'parameters': {'min_year': '1991',
                               'max_year': '2001'},
                'specification': {'first': 'do this',
                                  'second': 'do that'},
                'type': 'cwl'}
        res = client.post(url_for('api.create_workflow'),
                          query_string={
                              "user": default_user.id_,
                              "organization": organization},
                          content_type='application/json',
                          data=json.dumps(data))

        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))
        workflow = Workflow.query.filter(
            Workflow.id_ == response_data.get('workflow_id')).first()
        # workflow exist in DB
        assert workflow
        workflow.specification == data['specification']
        workflow.parameters == data['parameters']
        workflow.type_ == data['type']
        # workflow workspace exist
        user_analyses_workspace = get_user_analyses_dir(
            organization, str(default_user.id_))
        workflow_workspace = os.path.join(
            tmp_shared_volume_path,
            user_analyses_workspace,
            str(workflow.id_))
        assert os.path.exists(workflow_workspace)


def test_create_workflow_wrong_user(app, db_session, tmp_shared_volume_path):
    """Test create workflow providing unknown user."""
    with app.test_client() as client:
        organization = 'default'
        random_user_uuid = uuid.uuid4()
        data = {'parameters': {'min_year': '1991',
                               'max_year': '2001'},
                'specification': {'first': 'do this',
                                  'second': 'do that'},
                'type': 'cwl'}
        res = client.post(url_for('api.create_workflow'),
                          query_string={
                              "user": random_user_uuid,
                              "organization": organization},
                          content_type='application/json',
                          data=json.dumps(data))

        assert res.status_code == 404
        response_data = json.loads(res.get_data(as_text=True))
        workflow = Workflow.query.filter(
            Workflow.id_ == response_data.get('workflow_id')).first()
        # workflow exist in DB
        assert not workflow
        # workflow workspace exist
        user_analyses_workspace = get_user_analyses_dir(
            organization, str(random_user_uuid))
        workflow_workspace = os.path.join(
            tmp_shared_volume_path,
            user_analyses_workspace)
        assert not os.path.exists(workflow_workspace)


def test_get_workflow_outputs_file(app, db_session, default_user,
                                   tmp_shared_volume_path):
    """Test download output file."""
    with app.test_client() as client:
        # create workflow
        organization = 'default'
        data = {'parameters': {'min_year': '1991',
                               'max_year': '2001'},
                'specification': {'first': 'do this',
                                  'second': 'do that'},
                'type': 'cwl'}
        res = client.post(url_for('api.create_workflow'),
                          query_string={
                              "user": default_user.id_,
                              "organization": organization},
                          content_type='application/json',
                          data=json.dumps(data))

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get('workflow_id')
        workflow = Workflow.query.filter(
            Workflow.id_ == workflow_uuid).first()
        # create file
        file_name = 'output name.csv'
        file_binary_content = b'1,2,3,4\n5,6,7,8'
        absolute_path_workflow_workspace = \
            os.path.join(tmp_shared_volume_path,
                         workflow.workspace_path)
        # write file in the workflow workspace under `outputs` directory
        file_path = os.path.join(absolute_path_workflow_workspace,
                                 'outputs',
                                 # we use `secure_filename` here because
                                 # we use it in server side when adding
                                 # files
                                 file_name)
        # because outputs directory doesn't exist by default
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb+') as f:
            f.write(file_binary_content)
        res = client.get(
            url_for('api.get_workflow_outputs_file', workflow_id=workflow_uuid,
                    file_name=file_name),
            query_string={"user": default_user.id_,
                          "organization": organization},
            content_type='application/json',
            data=json.dumps(data))
        assert res.data == file_binary_content


def test_get_workflow_outputs_file_with_path(app, db_session, default_user,
                                             tmp_shared_volume_path):
    """Test download output file prepended with path."""
    with app.test_client() as client:
        # create workflow
        organization = 'default'
        data = {'parameters': {'min_year': '1991',
                               'max_year': '2001'},
                'specification': {'first': 'do this',
                                  'second': 'do that'},
                'type': 'cwl'}
        res = client.post(url_for('api.create_workflow'),
                          query_string={
                              "user": default_user.id_,
                              "organization": organization},
                          content_type='application/json',
                          data=json.dumps(data))

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get('workflow_id')
        workflow = Workflow.query.filter(
            Workflow.id_ == workflow_uuid).first()
        # create file
        file_name = 'first/1991/output.csv'
        file_binary_content = b'1,2,3,4\n5,6,7,8'
        absolute_path_workflow_workspace = \
            os.path.join(tmp_shared_volume_path,
                         workflow.workspace_path)
        # write file in the workflow workspace under `outputs` directory
        file_path = os.path.join(absolute_path_workflow_workspace,
                                 'outputs',
                                 file_name)
        # because outputs directory doesn't exist by default
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb+') as f:
            f.write(file_binary_content)
        res = client.get(
            url_for('api.get_workflow_outputs_file', workflow_id=workflow_uuid,
                    file_name=file_name),
            query_string={"user": default_user.id_,
                          "organization": organization},
            content_type='application/json',
            data=json.dumps(data))
        assert res.data == file_binary_content
