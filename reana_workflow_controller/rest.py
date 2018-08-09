# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
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

"""REANA Workflow Controller REST API."""

import os
import traceback
from datetime import datetime
from uuid import UUID, uuid4

from flask import (Blueprint, abort, current_app, jsonify, request,
                   send_from_directory)
from reana_db.database import Session
from reana_db.models import Job, User, Workflow, WorkflowStatus
from werkzeug.exceptions import NotFound

from reana_workflow_controller.config import (DEFAULT_NAME_FOR_WORKFLOWS,
                                              WORKFLOW_QUEUES,
                                              WORKFLOW_TIME_FORMAT)
from reana_workflow_controller.errors import (REANAWorkflowControllerError,
                                              UploadPathError,
                                              WorkflowInexistentError,
                                              WorkflowNameError)
from reana_workflow_controller.tasks import (run_cwl_workflow,
                                             run_serial_workflow,
                                             run_yadage_workflow)
from reana_workflow_controller.utils import (create_workflow_workspace,
                                             list_directory_files)

START = 'start'
STOP = 'stop'
PAUSE = 'pause'
STATUSES = {START, STOP, PAUSE}

workflow_spec_to_task = {
    "yadage": run_yadage_workflow,
    "cwl": run_cwl_workflow
}

restapi_blueprint = Blueprint('api', __name__)


@restapi_blueprint.route('/workflows', methods=['GET'])
def get_workflows():  # noqa
    r"""Get all workflows.

    ---
    get:
      summary: Returns all workflows.
      description: >-
        This resource is expecting a user UUID. The
        information related to all workflows for a given user will be served
        as JSON
      operationId: get_workflows
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
      responses:
        200:
          description: >-
            Requests succeeded. The response contains the current workflows
            for a given user.
          schema:
            type: array
            items:
              type: object
              properties:
                id:
                  type: string
                name:
                  type: string
                status:
                  type: string
                user:
                  type: string
                created:
                  type: string
                started:
                  type: string
                finished:
                  type: string
          examples:
            application/json:
              [
                {
                  "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                  "name": "mytest-1",
                  "status": "running",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                  "started": "2018-06-13 09:48:35.66097",
                  "finished": "2018-06-13 09:49:35.66097",
                },
                {
                  "id": "3c9b117c-d40a-49e3-a6de-5f89fcada5a3",
                  "name": "mytest-2",
                  "status": "finished",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                  "started": "2018-06-13 09:48:35.66097",
                  "finished": "2018-06-13 09:49:35.66097"
                },
                {
                  "id": "72e3ee4f-9cd3-4dc7-906c-24511d9f5ee3",
                  "name": "mytest-3",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                  "started": "2018-06-13 09:48:35.66097",
                  "finished": "2018-06-13 09:49:35.66097"
                },
                {
                  "id": "c4c0a1a6-beef-46c7-be04-bf4b3beca5a1",
                  "name": "mytest-4",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                  "started": "No",
                  "finished": "No"
                }
              ]
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
        404:
          description: >-
            Request failed. User does not exist.
          examples:
            application/json:
              {
                "message": "User 00000000-0000-0000-0000-000000000000 does not
                            exist"
              }
        500:
          description: >-
            Request failed. Internal controller error.
          examples:
            application/json:
              {
                "message": "Internal workflow controller error."
              }
    """
    try:
        user_uuid = request.args['user']
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify(
                {'message': 'User {} does not exist'.format(user)}), 404
        workflows = []
        for workflow in user.workflows:
            workflow_response = {'id': workflow.id_,
                                 'name': _get_workflow_name(workflow),
                                 'status': workflow.status.name,
                                 'user': user_uuid,
                                 'created': workflow.created.
                                 strftime(WORKFLOW_TIME_FORMAT)}
            workflows.append(workflow_response)

        return jsonify(workflows), 200
    except ValueError:
        return jsonify({"message": "Malformed request."}), 400
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows', methods=['POST'])
def create_workflow():  # noqa
    r"""Create workflow and its workspace.

    ---
    post:
      summary: Create workflow and its workspace.
      description: >-
        This resource expects all necessary data to represent a workflow so
        it is stored in database and its workspace is created.
      operationId: create_workflow
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow
          in: body
          description: >-
            JSON object including workflow parameters and workflow
            specification in JSON format (`yadageschemas.load()` output)
            with necessary data to instantiate a yadage workflow.
          required: true
          schema:
            type: object
            properties:
              parameters:
                type: object
                description: Workflow parameters.
              specification:
                type: object
                description: >-
                  Yadage specification in JSON format.
              type:
                type: string
                description: Workflow type.
              name:
                type: string
                description: Workflow name. If empty name will be generated.
            required: [specification, type, name]
      responses:
        201:
          description: >-
            Request succeeded. The workflow has been created along
            with its workspace
          schema:
            type: object
            properties:
              message:
                type: string
              workflow_id:
                type: string
              workflow_name:
                type: string
          examples:
            application/json:
              {
                "message": "Workflow workspace has been created.",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac",
                "workflow_name": "mytest-1"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed
        404:
          description: >-
            Request failed. User does not exist.
          examples:
            application/json:
              {
                "message": "User 00000000-0000-0000-0000-000000000000 does not
                            exist"
              }
    """
    try:
        user_uuid = request.args['user']
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify(
                {'message': 'User with id:{} does not exist'.
                 format(user_uuid)}), 404
        workflow_uuid = str(uuid4())

        # Use name prefix user specified or use default name prefix
        # Actual name is prefix + autoincremented run_number.
        workflow_name = request.json.get('name', '')
        if workflow_name == '':
            workflow_name = DEFAULT_NAME_FOR_WORKFLOWS
        else:
            try:
                workflow_name.encode('ascii')
            except UnicodeEncodeError:
                # `workflow_name` contains something else than just ASCII.
                raise WorkflowNameError('Workflow name {} is not valid.'.
                                        format(workflow_name))
        # add spec and params to DB as JSON
        workflow = Workflow(id_=workflow_uuid,
                            name=workflow_name,
                            owner_id=request.args['user'],
                            specification=request.json['specification'],
                            parameters=request.json.get('parameters'),
                            type_=request.json['type'],
                            logs='')
        Session.add(workflow)
        Session.commit()
        create_workflow_workspace(workflow.get_workspace())
        return jsonify({'message': 'Workflow workspace created',
                        'workflow_id': workflow.id_,
                        'workflow_name': _get_workflow_name(workflow)}), 201

    except (WorkflowNameError, KeyError) as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id_or_name>/workspace',
                         methods=['POST'])
def upload_file(workflow_id_or_name):
    r"""Upload file to workspace.

    ---
    post:
      summary: Adds a file to the workspace.
      description: >-
        This resource is expecting a workflow UUID and a file to place in the
        workspace.
      operationId: upload_file
      consumes:
        - multipart/form-data
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id_or_name
          in: path
          description: Required. Workflow UUID or name.
          required: true
          type: string
        - name: file_content
          in: formData
          description: Required. File to add to the workspace.
          required: true
          type: file
        - name: file_name
          in: query
          description: Required. File name.
          required: true
          type: string
      responses:
        200:
          description: >-
            Request succeeded. The file has been added to the workspace.
          schema:
            type: object
            properties:
              message:
                type: string
          examples:
            application/json:
              {
                "message": "`file_name` has been successfully uploaded.",
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed
        404:
          description: >-
            Request failed. Workflow does not exist.
          schema:
            type: object
            properties:
              message:
                type: string
          examples:
            application/json:
              {
                "message": "Workflow cdcf48b1-c2f3-4693-8230-b066e088c6ac does
                            not exist",
              }
        500:
          description: >-
            Request failed. Internal controller error.
    """
    try:
        user_uuid = request.args['user']
        file_ = request.files['file_content']
        full_file_name = request.args['file_name']
        if not full_file_name:
            raise ValueError('The file transferred needs to have name.')

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name,
                                                   user_uuid)

        filename = full_file_name.split("/")[-1]

        # Remove starting '/' in path
        if full_file_name[0] == '/':
            full_file_name = full_file_name[1:]
        elif '..' in full_file_name.split("/"):
            raise UploadPathError('Path cannot contain "..".')
        absolute_workspace_path = os.path.join(
          current_app.config['SHARED_VOLUME_PATH'],
          workflow.get_workspace())
        if len(full_file_name.split("/")) > 1:
            dirs = full_file_name.split("/")[:-1]
            absolute_workspace_path = os.path.join(absolute_workspace_path,
                                                   "/".join(dirs))
            if not os.path.exists(absolute_workspace_path):
                os.makedirs(absolute_workspace_path)

        file_.save(os.path.join(absolute_workspace_path, filename))
        return jsonify(
          {'message': '{} has been successfully uploaded.'.format(
            full_file_name)}), 200

    except WorkflowInexistentError:
        return jsonify({'message': 'REANA_WORKON is set to {0}, but '
                                   'that workflow does not exist. '
                                   'Please set your REANA_WORKON environment'
                                   'variable appropriately.'.
                                   format(workflow_id_or_name)}), 404
    except (KeyError, ValueError) as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route(
    '/workflows/<workflow_id_or_name>/workspace/<path:file_name>',
    methods=['GET'])
def download_file(workflow_id_or_name, file_name):  # noqa
    r"""Download a file from the workspace.

    ---
    get:
      summary: Returns the requested file.
      description: >-
        This resource is expecting a workflow UUID and a filename existing
        inside the workspace to return its content.
      operationId: download_file
      produces:
        - multipart/form-data
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id_or_name
          in: path
          description: Required. Workflow UUID or name
          required: true
          type: string
        - name: file_name
          in: path
          description: Required. Name (or path) of the file to be downloaded.
          required: true
          type: string
      responses:
        200:
          description: >-
            Requests succeeded. The file has been downloaded.
          schema:
            type: file
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
        404:
          description: >-
            Request failed. `file_name` does not exist.
          examples:
            application/json:
              {
                "message": "input.csv does not exist"
              }
        500:
          description: >-
            Request failed. Internal controller error.
          examples:
            application/json:
              {
                "message": "Internal workflow controller error."
              }
    """
    try:
        user_uuid = request.args['user']
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify(
                {'message': 'User {} does not exist'.format(user)}), 404

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name,
                                                   user_uuid)

        absolute_workflow_workspace_path = os.path.join(
          current_app.config['SHARED_VOLUME_PATH'],
          workflow.get_workspace())
        return send_from_directory(absolute_workflow_workspace_path,
                                   file_name,
                                   mimetype='multipart/form-data',
                                   as_attachment=True), 200

    except WorkflowInexistentError:
        return jsonify({'message': 'REANA_WORKON is set to {0}, but '
                                   'that workflow does not exist. '
                                   'Please set your REANA_WORKON environment '
                                   'variable appropriately.'.
                                   format(workflow_id_or_name)}), 404
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except NotFound as e:
        return jsonify(
            {"message": "{0} does not exist.".format(file_name)}), 404
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id_or_name>/workspace',
                         methods=['GET'])
def get_files(workflow_id_or_name):  # noqa
    r"""List all files contained in a workspace.

    ---
    get:
      summary: Returns the workspace file list.
      description: >-
        This resource retrieves the file list of a workspace, given
        its workflow UUID.
      operationId: get_files
      produces:
        - multipart/form-data
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id_or_name
          in: path
          description: Required. Workflow UUID or name.
          required: true
          type: string
      responses:
        200:
          description: >-
            Requests succeeded. The list of code|input|output files has been
            retrieved.
          schema:
            type: array
            items:
              type: object
              properties:
                name:
                  type: string
                last-modified:
                  type: string
                  format: date-time
                size:
                  type: integer
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
        404:
          description: >-
            Request failed. Workflow does not exist.
          examples:
            application/json:
              {
                "message": "Workflow 256b25f4-4cfb-4684-b7a8-73872ef455a1 does
                            not exist."
              }
        500:
          description: >-
            Request failed. Internal controller error.
          examples:
            application/json:
              {
                "message": "Internal workflow controller error."
              }
    """
    try:
        user_uuid = request.args['user']
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify(
                {'message': 'User {} does not exist'.format(user)}), 404

        file_type = request.args.get('file_type') \
            if request.args.get('file_type') else 'input'

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name,
                                                   user_uuid)

        file_list = list_directory_files(os.path.join(
          current_app.config['SHARED_VOLUME_PATH'],
          workflow.get_workspace()))
        return jsonify(file_list), 200

    except WorkflowInexistentError:
        return jsonify({'message': 'REANA_WORKON is set to {0}, but '
                                   'that workflow does not exist. '
                                   'Please set your REANA_WORKON environment '
                                   'variable appropriately.'.
                                   format(workflow_id_or_name)}), 404
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id_or_name>/logs',
                         methods=['GET'])
def get_workflow_logs(workflow_id_or_name):  # noqa
    r"""Get workflow logs from a workflow engine.

    ---
    get:
      summary: Returns logs of a specific workflow from a workflow engine.
      description: >-
        This resource is expecting a workflow UUID and a filename to return
        its outputs.
      operationId: get_workflow_logs
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id_or_name
          in: path
          description: Required. Workflow UUID or name.
          required: true
          type: string
      responses:
        200:
          description: >-
            Request succeeded. Info about workflow, including the status is
            returned.
          schema:
            type: object
            properties:
              workflow_id:
                type: string
              workflow_name:
                type: string
              logs:
                type: string
              user:
                type: string
          examples:
            application/json:
              {
                "workflow_id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                "workflow_name": "mytest-1",
                "logs": "<Workflow engine log output>",
                "user": "00000000-0000-0000-0000-000000000000"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
        404:
          description: >-
            Request failed. User does not exist.
          examples:
            application/json:
              {
                "message": "User 00000000-0000-0000-0000-000000000000 does not
                            exist"
              }
        500:
          description: >-
            Request failed. Internal controller error.
          examples:
            application/json:
              {
                "message": "Internal workflow controller error."
              }
    """
    try:
        user_uuid = request.args['user']

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name,
                                                   user_uuid)

        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id_or_name)}), 403

        return jsonify({'workflow_id': workflow.id_,
                        'workflow_name': _get_workflow_name(workflow),
                        'logs': workflow.logs or "",
                        'user': user_uuid}), 200

    except WorkflowInexistentError:
        return jsonify({'message': 'REANA_WORKON is set to {0}, but '
                                   'that workflow does not exist. '
                                   'Please set your REANA_WORKON environment '
                                   'variable appropriately.'.
                                   format(workflow_id_or_name)}), 404
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/yadage/remote', methods=['POST'])
def run_yadage_workflow_from_remote_endpoint():  # noqa
    r"""Create a new yadage workflow from a remote repository.

    ---
    post:
      summary: Creates a new yadage workflow from a remote repository.
      description: >-
        This resource is expecting JSON data with all the necessary information
        to instantiate a yadage workflow from a remote repository.
      operationId: run_yadage_workflow_from_remote
      consumes:
        - application/json
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_data
          in: body
          description: >-
            Workflow information in JSON format with all the necessary data to
            instantiate a yadage workflow from a remote repository such as
            GitHub.
          required: true
          schema:
            type: object
            properties:
              toplevel:
                type: string
                description: >-
                  Yadage toplevel argument. It represents the remote repository
                  where the workflow should be pulled from.
              workflow:
                type: string
                description: >-
                  Yadage workflow parameter. It represents the name of the
                  workflow spec file name inside the remote repository.
              nparallel:
                type: integer
              preset_pars:
                type: object
                description: Workflow parameters.
      responses:
        200:
          description: >-
            Request succeeded. The workflow has been instantiated.
          schema:
            type: object
            properties:
              message:
                type: string
              workflow_id:
                type: string
              workflow_name:
                type: string
          examples:
            application/json:
              {
                "message": "Workflow successfully launched",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac",
                "workflow_name": "mytest-1"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed
    """
    try:
        if request.json:
            # get workflow UUID from client in order to retrieve its workspace
            # from DB
            workflow_workspace = ''
            kwargs = {
                "workflow_workspace": workflow_workspace,
                "workflow": request.json['workflow'],
                "toplevel": request.json['toplevel'],
                "parameters": request.json['preset_pars']
            }
            resultobject = run_yadage_workflow.apply_async(
                kwargs=kwargs,
                queue=WORKFLOW_QUEUES['yadage'])
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': resultobject.id,
                            'workflow_name': resultobject.name}), 200

    except (KeyError, ValueError):
        traceback.print_exc()
        abort(400)


@restapi_blueprint.route('/yadage/spec', methods=['POST'])
def run_yadage_workflow_from_spec_endpoint():  # noqa
    r"""Create a new yadage workflow.

    ---
    post:
      summary: Creates a new yadage workflow from a specification file.
      description: This resource is expecting a JSON yadage specification.
      operationId: run_yadage_workflow_from_spec
      consumes:
        - application/json
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow
          in: body
          description: >-
            JSON object including workflow parameters and workflow
            specification in JSON format (`yadageschemas.load()` output)
            with necessary data to instantiate a yadage workflow.
          required: true
          schema:
            type: object
            properties:
              parameters:
                type: object
                description: Workflow parameters.
              workflow_spec:
                type: object
                description: >-
                  Yadage specification in JSON format.
      responses:
        200:
          description: >-
            Request succeeded. The workflow has been instantiated.
          schema:
            type: object
            properties:
              message:
                type: string
              workflow_id:
                type: string
              workflow_name:
                type: string
          examples:
            application/json:
              {
                "message": "Workflow successfully launched",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac",
                "workflow_name": "mytest-1"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed
    """
    try:
        # hardcoded until confirmation from `yadage`
        if request.json:
            # get workflow UUID from client in order to retrieve its workspace
            # from DB
            workflow_workspace = ''
            kwargs = {
                "workflow_workspace": workflow_workspace,
                "workflow_json": request.json['workflow_spec'],
                "parameters": request.json['parameters']
            }
            resultobject = run_yadage_workflow.apply_async(
                kwargs=kwargs,
                queue=WORKFLOW_QUEUES['yadage']
            )
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': resultobject.id,
                            'workflow_name': resultobject.name}), 200

    except (KeyError, ValueError):
        traceback.print_exc()
        abort(400)


@restapi_blueprint.route('/cwl/remote', methods=['POST'])
def run_cwl_workflow_from_remote_endpoint():  # noqa
    r"""Create a new cwl workflow from a remote repository.

    ---
    post:
      summary: Creates a new cwl workflow from a remote repository.
      description: >-
        This resource is expecting JSON data with all the necessary information
        to instantiate a cwl workflow from a remote repository.
      operationId: run_cwl_workflow_from_remote
      consumes:
        - application/json
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_data
          in: body
          description: >-
            Workflow information in JSON format with all the necessary data to
            instantiate a cwl workflow from a remote repository such as
            GitHub.
          required: true
          schema:
            type: object
            properties:
              toplevel:
                type: string
                description: >-
                  cwl toplevel argument. It represents the remote repository
                  where the workflow should be pulled from.
              workflow:
                type: string
                description: >-
                  cwl workflow parameter. It represents the name of the
                  workflow spec file name inside the remote repository.
              nparallel:
                type: integer
              preset_pars:
                type: object
                description: Workflow parameters.
      responses:
        200:
          description: >-
            Request succeeded. The workflow has been instantiated.
          schema:
            type: object
            properties:
              message:
                type: string
              workflow_id:
                type: string
              workflow_name:
                type: string
          examples:
            application/json:
              {
                "message": "Workflow successfully launched",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac",
                "workflow_name": "mytest-1"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed
    """
    try:
        if request.json:
            resultobject = run_cwl_workflow.apply_async(
                args=[request.json],
                queue=WORKFLOW_QUEUES['cwl']
            )
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': resultobject.id,
                            'workflow_name': resultobject.name}), 200

    except (KeyError, ValueError):
        traceback.print_exc()
        abort(400)


@restapi_blueprint.route('/workflows/<workflow_id_or_name>/status',
                         methods=['GET'])
def get_workflow_status(workflow_id_or_name):  # noqa
    r"""Get workflow status.

    ---
    get:
      summary: Get workflow status.
      description: >-
        This resource reports the status of workflow.
      operationId: get_workflow_status
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id_or_name
          in: path
          description: Required. Workflow UUID or name.
          required: true
          type: string
      responses:
        200:
          description: >-
            Request succeeded. Info about workflow, including the status is
            returned.
          schema:
            type: object
            properties:
              id:
                type: string
              name:
                type: string
              created:
                type: string
              status:
                type: string
              user:
                type: string
              logs:
                type: string
              progress:
                type: object
          examples:
            application/json:
              {
                "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                "name": "mytest-1",
                "created": "2018-06-13T09:47:35.66097",
                "status": "running",
                "user": "00000000-0000-0000-0000-000000000000"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
          examples:
            application/json:
              {
                "message": "Malformed request."
              }
        403:
          description: >-
            Request failed. User is not allowed to access workflow.
          examples:
            application/json:
              {
                "message": "User 00000000-0000-0000-0000-000000000000
                            is not allowed to access workflow
                            256b25f4-4cfb-4684-b7a8-73872ef455a1"
              }
        404:
          description: >-
            Request failed. Either User or Workflow does not exist.
          examples:
            application/json:
              {
                "message": "User 00000000-0000-0000-0000-000000000000 does not
                            exist"
              }
            application/json:
              {
                "message": "Workflow 256b25f4-4cfb-4684-b7a8-73872ef455a1
                            does not exist"
              }
        500:
          description: >-
            Request failed. Internal controller error.
    """

    try:
        user_uuid = request.args['user']
        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name,
                                                   user_uuid)
        workflow_logs = _get_workflow_logs(workflow)
        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id_or_name)}), 403

        current_job_progress = _get_current_job_progress(workflow.id_)
        cmd_and_step_name = {}
        try:
            current_job_id, cmd_and_step_name = current_job_progress.\
                popitem()
        except Exception:
            pass
        run_started_at = None
        if workflow.run_started_at:
            run_started_at = workflow.run_started_at.\
                strftime(WORKFLOW_TIME_FORMAT)
        initial_progress_status = {'total': 0, 'job_ids': []}
        progress = {'total':
                    workflow.job_progress.get('total') or
                    initial_progress_status,
                    'running':
                    workflow.job_progress.get('running') or
                    initial_progress_status,
                    'finished':
                    workflow.job_progress.get('finished') or
                    initial_progress_status,
                    'failed':
                    workflow.job_progress.get('failed') or
                    initial_progress_status,
                    'current_command':
                    cmd_and_step_name.get('prettified_cmd'),
                    'current_step_name':
                    cmd_and_step_name.get('current_job_name'),
                    'run_started_at':
                    run_started_at
                    }

        return jsonify({'id': workflow.id_,
                        'name': _get_workflow_name(workflow),
                        'created':
                        workflow.created.strftime(WORKFLOW_TIME_FORMAT),
                        'status': workflow.status.name,
                        'progress': progress,
                        'user': user_uuid,
                        'logs': workflow_logs}), 200
    except WorkflowInexistentError:
        return jsonify({'message': 'REANA_WORKON is set to {0}, but '
                                   'that workflow does not exist. '
                                   'Please set your REANA_WORKON environment '
                                   'variable appropriately.'.
                                   format(workflow_id_or_name)}), 404
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id_or_name>/status',
                         methods=['PUT'])
def set_workflow_status(workflow_id_or_name):  # noqa
    r"""Set workflow status.

    ---
    put:
      summary: Set workflow status.
      description: >-
        This resource sets the status of workflow.
      operationId: set_workflow_status
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id_or_name
          in: path
          description: Required. Workflow UUID or name.
          required: true
          type: string
        - name: status
          in: query
          description: Required. New status.
          required: true
          type: string
        - name: parameters
          in: body
          description: Optional. Extra parameters for workflow status.
          required: false
          schema:
            type: object
      responses:
        200:
          description: >-
            Request succeeded. Info about workflow, including the status is
            returned.
          schema:
            type: object
            properties:
              message:
                type: string
              workflow_id:
                type: string
              workflow_name:
                type: string
              status:
                type: string
              user:
                type: string
          examples:
            application/json:
              {
                "message": "Workflow successfully launched",
                "workflow_id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                "workflow_name": "mytest-1",
                "status": "running",
                "user": "00000000-0000-0000-0000-000000000000"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
          examples:
            application/json:
              {
                "message": "Malformed request."
              }
        403:
          description: >-
            Request failed. User is not allowed to access workflow.
          examples:
            application/json:
              {
                "message": "User 00000000-0000-0000-0000-000000000000
                            is not allowed to access workflow
                            256b25f4-4cfb-4684-b7a8-73872ef455a1"
              }
        404:
          description: >-
            Request failed. Either User or Workflow does not exist.
          examples:
            application/json:
              {
                "message": "User 00000000-0000-0000-0000-000000000000 does not
                            exist"
              }
            application/json:
              {
                "message": "Workflow 256b25f4-4cfb-4684-b7a8-73872ef455a1
                            does not exist"
              }
        409:
          description: >-
            Request failed. The workflow could not be started due to a
            conflict.
          examples:
            application/json:
              {
                "message": "Workflow 256b25f4-4cfb-4684-b7a8-73872ef455a1
                            could not be started because it is already
                            running."
              }
        500:
          description: >-
            Request failed. Internal controller error.
        501:
          description: >-
            Request failed. The specified status change is not implemented.
          examples:
            application/json:
              {
                "message": "Status resume is not supported yet."
              }
    """

    try:
        user_uuid = request.args['user']
        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name,
                                                   user_uuid)
        status = request.args.get('status')
        if not (status in STATUSES):
            return jsonify({'message': 'Status {0} is not one of: {1}'.
                            format(status, ", ".join(STATUSES))}), 400

        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id_or_name)}), 403
        parameters = None
        if request.json:
            parameters = request.json.get('parameters')
        if status == START:
            return start_workflow(workflow, parameters)
        else:
            raise NotImplemented("Status {} is not supported yet"
                                 .format(status))
    except WorkflowInexistentError:
        return jsonify({'message': 'REANA_WORKON is set to {0}, but '
                                   'that workflow does not exist. '
                                   'Please set your REANA_WORKON environment '
                                   'variable appropriately.'.
                                   format(workflow_id_or_name)}), 404
    except REANAWorkflowControllerError as e:
        return jsonify({"message": str(e)}), 409
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except NotImplementedError as e:
        return jsonify({"message": str(e)}), 501
    except Exception as e:
        return jsonify({"message": str(e)}), 500


def start_workflow(workflow, parameters):
    """Start a workflow."""
    if workflow.status == WorkflowStatus.created:
        workflow.run_started_at = datetime.now()
        workflow.status = WorkflowStatus.running
        current_db_sessions = Session.object_session(workflow)
        current_db_sessions.add(workflow)
        current_db_sessions.commit()
        if workflow.type_ == 'yadage':
            return run_yadage_workflow_from_spec(workflow)
        elif workflow.type_ == 'cwl':
            return run_cwl_workflow_from_spec_endpoint(workflow)
        elif workflow.type_ == 'serial':
            return run_serial_workflow_from_spec(workflow, parameters)
        else:
            raise NotImplementedError(
                'Workflow type {} is not supported.'.format(workflow.type_))
    else:
        verb = "is" if workflow.status == WorkflowStatus.running else "has"
        message = \
            ("Workflow {id_} could not be started because it {verb}"
             " already {status}.").format(id_=workflow.id_, verb=verb,
                                          status=str(workflow.status.name))
        raise REANAWorkflowControllerError(message)


def run_yadage_workflow_from_spec(workflow):
    """Run a yadage workflow."""
    try:
        kwargs = {
            "workflow_uuid": str(workflow.id_),
            "workflow_workspace": workflow.get_workspace(),
            "workflow_json": workflow.specification,
            "parameters": workflow.parameters
        }
        if not os.environ.get("TESTS"):
            resultobject = run_yadage_workflow.apply_async(
                kwargs=kwargs,
                queue=WORKFLOW_QUEUES['yadage']
            )
        return jsonify({'message': 'Workflow successfully launched',
                        'workflow_id': workflow.id_,
                        'workflow_name': _get_workflow_name(workflow),
                        'status': workflow.status.name,
                        'user': str(workflow.owner_id)}), 200

    except(KeyError, ValueError):
        traceback.print_exc()
        abort(400)


def run_cwl_workflow_from_spec_endpoint(workflow):  # noqa
    """Run a CWL workflow."""
    try:
        parameters = None
        if workflow.parameters:
            if 'input' in workflow.parameters:
                parameters = workflow.parameters['input']
        kwargs = {
            "workflow_uuid": str(workflow.id_),
            "workflow_workspace": workflow.get_workspace(),
            "workflow_json": workflow.specification,
            "parameters": parameters
        }
        if not os.environ.get("TESTS"):
            resultobject = run_cwl_workflow.apply_async(
                kwargs=kwargs,
                queue=WORKFLOW_QUEUES['cwl']
            )
        return jsonify({'message': 'Workflow successfully launched',
                        'workflow_id': str(workflow.id_),
                        'workflow_name': _get_workflow_name(workflow),
                        'status': workflow.status.name,
                        'user': str(workflow.owner_id)}), 200

    except (KeyError, ValueError) as e:
        print(e)
        # traceback.print_exc()
        abort(400)


def run_serial_workflow_from_spec(workflow, parameters):
    """Run a serial workflow."""
    try:
        kwargs = {
            "workflow_uuid": str(workflow.id_),
            "workflow_workspace": workflow.get_workspace(),
            "workflow_json": workflow.specification,
            "parameters": {**workflow.parameters, **parameters},
        }
        if not os.environ.get("TESTS"):
            resultobject = run_serial_workflow.apply_async(
                kwargs=kwargs,
                queue=WORKFLOW_QUEUES['serial'])
        return jsonify({'message': 'Workflow successfully launched',
                        'workflow_id': str(workflow.id_),
                        'workflow_name': _get_workflow_name(workflow),
                        'status': workflow.status.name,
                        'user': str(workflow.owner_id)}), 200

    except(KeyError, ValueError):
        traceback.print_exc()
        abort(400)


def _get_workflow_name(workflow):
    """Return a name of a Workflow.

    :param workflow: Workflow object which name should be returned.
    :type workflow: reana-commons.models.Workflow
    """
    return workflow.name + '.' + str(workflow.run_number)


def _get_workflow_by_name(workflow_name, user_uuid):
    """From Workflows named as `workflow_name` the latest run_number.

    Only use when you are sure that workflow_name is not UUIDv4.

    :rtype: reana-commons.models.Workflow
    """
    workflow = Workflow.query.filter(
        Workflow.name == workflow_name,
        Workflow.owner_id == user_uuid). \
        order_by(Workflow.run_number.desc()).first()
    if not workflow:
        raise WorkflowInexistentError(
            'REANA_WORKON is set to {0}, but '
            'that workflow does not exist. '
            'Please set your REANA_WORKON environment '
            'variable appropriately.'.
            format(workflow_name))
    return workflow


def _get_workflow_by_uuid(workflow_uuid):
    """Get Workflow with UUIDv4.

    :param workflow_uuid: UUIDv4 of a Workflow.
    :type workflow_uuid: String representing a valid UUIDv4.

    :rtype: reana-commons.models.Workflow
    """
    workflow = Workflow.query.filter(Workflow.id_ ==
                                     workflow_uuid).first()
    if not workflow:
        raise WorkflowInexistentError(
            'REANA_WORKON is set to {0}, but '
            'that workflow does not exist. '
            'Please set your REANA_WORKON environment '
            'variable appropriately.'.
            format(workflow_uuid))
    return workflow


def _get_workflow_with_uuid_or_name(uuid_or_name, user_uuid):
    """Get Workflow from database with uuid or name.

    :param uuid_or_name: String representing a valid UUIDv4 or valid
        Workflow name. Valid name contains only ASCII alphanumerics.

        Name might be in format 'reana.workflow.123' with arbitrary
        number of dot-delimited substrings, where last substring specifies
        the run number of the workflow this workflow name refers to.

        If name does not contain a valid run number, but it is a valid name,
        workflow with latest run number of all the workflows with this name
        is returned.
    :type uuid_or_name: String

    :rtype: reana-commons.models.Workflow
    """
    # Check existence
    if not uuid_or_name:
        raise WorkflowNameError('No Workflow was specified.')

    # Check validity
    try:
        uuid_or_name.encode('ascii')
    except UnicodeEncodeError:
        # `workflow_name` contains something else than just ASCII.
        raise WorkflowNameError('Workflow name {} is not valid.'.
                                format(uuid_or_name))

    # Check if UUIDv4
    try:
        # is_uuid = UUID(uuid_or_name, version=4)
        is_uuid = UUID('{' + uuid_or_name + '}', version=4)
    except (TypeError, ValueError):
        is_uuid = None

    if is_uuid:
        # `uuid_or_name` is an UUIDv4.
        # Search with it since it is expected to be unique.
        return _get_workflow_by_uuid(uuid_or_name)

    else:
        # `uuid_or_name` is not and UUIDv4. Expect it is a name.

        # Expect name might be in format 'reana.workflow.123' with arbitrary
        # number of dot-delimited substring, where last substring specifies
        # the run_number of the workflow this workflow name refers to.

        # Possible candidates for names are e.g. :
        # 'workflow_name' -> ValueError
        # 'workflow.name' -> True, True
        # 'workflow.name.123' -> True, True
        # '123.' -> True, False
        # '' -> ValueError
        # '.123' -> False, True
        # '..' -> False, False
        # '123.12' -> True, True
        # '123.12.' -> True, False

        # Try to split the dot-separated string.
        try:
            workflow_name, run_number = uuid_or_name.rsplit('.', maxsplit=1)
        except ValueError:
            # Couldn't split. Probably not a dot-separated string.
            #  -> Search with `uuid_or_name`
            return _get_workflow_by_name(uuid_or_name, user_uuid)

        # Check if `run_number` was specified
        if not run_number:
            # No `run_number` specified.
            # -> Search by `workflow_name`
            return _get_workflow_by_name(workflow_name, user_uuid)

        # `run_number` was specified.
        # Check `run_number` is valid.
        if not run_number.isdigit():
            # `uuid_or_name` was split, so it is a dot-separated string
            # but it didn't contain a valid `run_number`.
            # Assume that this dot-separated string is the name of
            # the workflow and search with it.
            return _get_workflow_by_name(uuid_or_name, user_uuid)

        # `run_number` is valid.
        # Search by `run_number` since it is a primary key.
        workflow = Workflow.query.filter(
            Workflow.name == workflow_name,
            Workflow.run_number == run_number,
            Workflow.owner_id == user_uuid).\
            one_or_none()
        if not workflow:
            raise WorkflowInexistentError(
                'REANA_WORKON is set to {0}, but '
                'that workflow does not exist. '
                'Please set your REANA_WORKON environment '
                'variable appropriately.'.
                format(workflow_name, run_number))

        return workflow


def _get_workflow_logs(workflow):
    """Return the logs for all jobs of a workflow."""
    jobs = Session.query(Job).filter_by(workflow_uuid=workflow.id_).all()
    all_logs = ''
    for job in jobs:
        all_logs += job.logs or ''
    return all_logs


def _get_current_job_progress(workflow_id):
    """Return job."""
    current_job_commands = {}
    workflow_jobs = Session.query(Job).filter_by(
        workflow_uuid=workflow_id).all()
    for workflow_job in workflow_jobs:
        job = Session.query(Job).filter_by(id_=workflow_job.id_).\
            order_by(Job.created.desc()).first()
        if job:
            current_job_commands[str(job.id_)] = {
                'prettified_cmd': job.prettified_cmd,
                'current_job_name': job.name}
    return current_job_commands
