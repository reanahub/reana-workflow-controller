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
from uuid import uuid4

from flask import Blueprint, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import NotFound
from werkzeug.utils import secure_filename

from reana_workflow_controller.config import SHARED_VOLUME_PATH
from reana_workflow_controller.models import WorkflowStatus

from .factory import db
from .models import User, Workflow, WorkflowStatus
from .tasks import run_cwl_workflow, run_yadage_workflow
from .utils import (create_workflow_workspace, get_analysis_files_dir,
                    list_directory_files)

START = 'start'
STOP = 'stop'
PAUSE = 'pause'
STATUSES = {START, STOP, PAUSE}

organization_to_queue = {
    'alice': 'alice-queue',
    'atlas': 'atlas-queue',
    'lhcb': 'lhcb-queue',
    'cms': 'cms-queue',
    'default': 'default-queue'
}

workflow_spec_to_task = {
    "yadage": run_yadage_workflow,
    "cwl": run_cwl_workflow
}

restapi_blueprint = Blueprint('api', __name__)


@restapi_blueprint.before_request
def before_request():
    """Retrieve organization from request."""
    try:
        db.choose_organization(request.args['organization'])
    except KeyError as e:
        return jsonify({"message": "An organization should be provided"}), 400
    except ValueError as e:
        return jsonify({"message": str(e)}), 404
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows', methods=['GET'])
def get_workflows():  # noqa
    r"""Get all workflows.

    ---
    get:
      summary: Returns all workflows.
      description: >-
        This resource is expecting an organization name and an user UUID. The
        information related to all workflows for a given user will be served
        as JSON
      operationId: get_workflows
      produces:
        - application/json
      parameters:
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
      responses:
        200:
          description: >-
            Requests succeeded. The response contains the current workflows
            for a given user and organization.
          schema:
            type: array
            items:
              type: object
              properties:
                id:
                  type: string
                organization:
                  type: string
                status:
                  type: string
                user:
                  type: string
          examples:
            application/json:
              [
                {
                  "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                  "organization": "default_org",
                  "status": "running",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "3c9b117c-d40a-49e3-a6de-5f89fcada5a3",
                  "organization": "default_org",
                  "status": "finished",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "72e3ee4f-9cd3-4dc7-906c-24511d9f5ee3",
                  "organization": "default_org",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "c4c0a1a6-beef-46c7-be04-bf4b3beca5a1",
                  "organization": "default_org",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000"
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
                "message": "Either organization or user does not exist."
              }
    """
    try:
        organization = request.args['organization']
        user_uuid = request.args['user']
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify(
                {'message': 'User {} does not exist'.format(user)}), 404

        workflows = []
        for workflow in user.workflows:
            workflows.append({'id': workflow.id_,
                              'status': workflow.status.name,
                              'organization': organization,
                              'user': user_uuid})

        return jsonify(workflows), 200
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
        This resource expects a POST call to create a new workflow workspace.
      operationId: create_workflow
      produces:
        - application/json
      parameters:
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
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
          examples:
            application/json:
              {
                "message": "Workflow workspace has been created.",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
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
        organization = request.args['organization']
        user_uuid = request.args['user']
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify(
                {'message': 'User {} does not exist'.format(user)}), 404

        workflow_uuid = str(uuid4())
        workflow_workspace, _ = create_workflow_workspace(
            organization,
            user_uuid,
            workflow_uuid)
        # add spec and params to DB as JSON
        workflow = Workflow(id_=workflow_uuid,
                            workspace_path=workflow_workspace,
                            owner_id=request.args['user'],
                            specification=request.json['specification'],
                            parameters=request.json['parameters'],
                            type_=request.json['type'])
        db.session.add(workflow)
        db.session.commit()
        return jsonify({'message': 'Workflow workspace created',
                        'workflow_id': workflow_uuid}), 201
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id>/workspace',
                         methods=['POST'])
def seed_workflow_workspace(workflow_id):
    r"""Seed workflow workspace.

    ---
    post:
      summary: Adds a file to the workflow workspace.
      description: >-
        This resource is expecting a workflow UUID and a file to place in the
        workflow workspace.
      operationId: seed_workflow_files
      consumes:
        - multipart/form-data
      produces:
        - application/json
      parameters:
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id
          in: path
          description: Required. Workflow UUID.
          required: true
          type: string
        - name: file_content
          in: formData
          description: Required. File to add to the workflow workspace.
          required: true
          type: file
        - name: file_name
          in: query
          description: Required. File name.
          required: true
          type: string
        - name: file_type
          in: query
          description: Required. If set to `input`, the file will be placed
                       under `workspace/inputs/` whereas if it is of type
                       `code` it will live under `workspace/code/`. By default
                       it set to `input`.
          required: false
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
              workflow_id:
                type: string
          examples:
            application/json:
              {
                "message": "input.csv has been successfully transferred.",
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
        file_ = request.files['file_content']
        # file_name = secure_filename(request.args['file_name'])
        full_file_name = request.args['file_name']
        if not full_file_name:
            raise ValueError('The file transferred needs to have name.')

        file_type = request.args.get('file_type') \
            if request.args.get('file_type') else 'input'

        workflow = Workflow.query.filter(Workflow.id_ == workflow_id).first()
        if workflow:
            filename = full_file_name.split("/")[-1]
            path = get_analysis_files_dir(workflow, file_type,
                                          'seed')
            if len(full_file_name.split("/")) > 1 and not \
               os.path.isabs(full_file_name):
                dirs = full_file_name.split("/")[:-1]
                path = os.path.join(path, "/".join(dirs))
                if not os.path.exists(path):
                    os.makedirs(path)

            file_.save(os.path.join(path, filename))
            return jsonify({'message': 'File successfully transferred'}), 200
        else:
            return jsonify({'message': 'Workflow {0} does not exist.'.format(
                           workflow_id)}), 404
    except (KeyError, ValueError) as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route(
    '/workflows/<workflow_id>/workspace/outputs/<path:file_name>',
    methods=['GET'])
def get_workflow_outputs_file(workflow_id, file_name):  # noqa
    r"""Get all workflows.

    ---
    get:
      summary: Returns the requested file.
      description: >-
        This resource is expecting a workflow UUID and a filename to return
        its content.
      operationId: get_workflow_outputs_file
      produces:
        - multipart/form-data
      parameters:
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id
          in: path
          description: Required. Workflow UUID.
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
                "message": "Either organization or user does not exist."
              }
    """
    try:
        user_uuid = request.args['user']
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify(
                {'message': 'User {} does not exist'.format(user)}), 404

        workflow = Workflow.query.filter(Workflow.id_ == workflow_id).first()
        if workflow:
            outputs_directory = get_analysis_files_dir(workflow, 'output')
            return send_from_directory(outputs_directory,
                                       file_name,
                                       mimetype='multipart/form-data',
                                       as_attachment=True), 200
        else:
            return jsonify({'message': 'Workflow {} does not exist.'.
                            format(str(workflow_id))}), 404
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except NotFound as e:
        return jsonify(
            {"message": "{0} does not exist.".format(file_name)}), 404
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id>/workspace',
                         methods=['GET'])
def get_workflow_files(workflow_id):  # noqa
    r"""List all workflow code/input/output files.

    ---
    get:
      summary: Returns the list of code|input|output files for a specific
               workflow.
      description: >-
        This resource is expecting a workflow UUID and a filename to return
        its list of code|input|output files.
      operationId: get_workflow_files
      produces:
        - multipart/form-data
      parameters:
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id
          in: path
          description: Required. Workflow UUID.
          required: true
          type: string
        - name: file_type
          in: query
          description: Required. The file will be retrieved from the
                       corresponding directory `workspace/<file_type>`.
                       Possible values are `code`, `input` and `output`.
                       `input` is the default value.
          required: false
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
                "message": "Either organization or user does not exist."
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

        workflow = Workflow.query.filter(Workflow.id_ == workflow_id).first()
        if workflow:
            file_list = list_directory_files(
                get_analysis_files_dir(workflow, file_type))
            return jsonify(file_list), 200
        else:
            return jsonify({'message': 'Workflow {} does not exist.'.
                            format(str(workflow_id))}), 404

    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id>/logs',
                         methods=['GET'])
def get_workflow_logs(workflow_id):  # noqa
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
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id
          in: path
          description: Required. Workflow UUID.
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
              organization:
                type: string
              logs:
                type: string
              user:
                type: string
          examples:
            application/json:
              {
                "workflow_id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                "organization": "default_org",
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
                "message": "Either organization or user does not exist."
              }
    """
    try:
        organization = request.args['organization']
        user_uuid = request.args['user']
        workflow = Workflow.query.filter(Workflow.id_ == workflow_id).first()
        if not workflow:
            return jsonify({'message': 'Workflow {} does not exist'.
                            format(workflow_id)}), 404
        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id)}), 403

        return jsonify({'workflow_id': workflow.id_,
                        'logs': workflow.logs or "",
                        'organization': organization,
                        'user': user_uuid}), 200
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
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
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
          examples:
            application/json:
              {
                "message": "Workflow successfully launched",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
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
            queue = organization_to_queue[request.args.get('organization')]
            resultobject = run_yadage_workflow.apply_async(
                kwargs=kwargs,
                queue='yadage-{}'.format(queue)
            )
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': resultobject.id}), 200

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
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
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
          examples:
            application/json:
              {
                "message": "Workflow successfully launched",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
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
            queue = organization_to_queue[request.args.get('organization')]
            resultobject = run_yadage_workflow.apply_async(
                kwargs=kwargs,
                queue='yadage-{}'.format(queue)
            )
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': resultobject.id}), 200

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
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
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
          examples:
            application/json:
              {
                "message": "Workflow successfully launched",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed
    """
    try:
        if request.json:
            queue = organization_to_queue[request.args.get('organization')]
            resultobject = run_cwl_workflow.apply_async(
                args=[request.json],
                queue='cwl-{}'.format(queue)
            )
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': resultobject.id}), 200

    except (KeyError, ValueError):
        traceback.print_exc()
        abort(400)


@restapi_blueprint.route('/workflows/<workflow_id>/status', methods=['GET'])
def get_workflow_status(workflow_id):  # noqa
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
        - name: organization
          in: query
          description: Required. Organization which the workflow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id
          in: path
          description: Required. Workflow UUID.
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
              organization:
                type: string
              status:
                type: string
              user:
                type: string
          examples:
            application/json:
              {
                "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                "organization": "default_org",
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
        organization = request.args['organization']
        user_uuid = request.args['user']
        workflow = Workflow.query.filter(Workflow.id_ == workflow_id).first()
        if not workflow:
            return jsonify({'message': 'Workflow {} does not exist'.
                            format(workflow_id)}), 404
        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id)}), 403

        return jsonify({'id': workflow.id_,
                        'status': workflow.status.name,
                        'organization': organization,
                        'user': user_uuid}), 200
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@restapi_blueprint.route('/workflows/<workflow_id>/status', methods=['PUT'])
def set_workflow_status(workflow_id):  # noqa
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
        - name: organization
          in: query
          description: Required. Organization which the workflow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id
          in: path
          description: Required. Workflow UUID.
          required: true
          type: string
        - name: status
          in: body
          description: Required. New status.
          required: true
          schema:
              type: string
              description: Required. New status.
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
              organization:
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
                "organization": "default_org",
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
        organization = request.args['organization']
        user_uuid = request.args['user']
        workflow = Workflow.query.filter(Workflow.id_ == workflow_id).first()
        status = request.json
        if not (status in STATUSES):
            return jsonify({'message': 'Status {0} is not one of: {1}'.
                            format(status, ", ".join(STATUSES))}), 400
        if not workflow:
            return jsonify({'message': 'Workflow {} does not exist.'.
                            format(workflow_id)}), 404
        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id)}), 403
        if status == START:
            return start_workflow(organization, workflow)
        else:
            raise NotImplemented("Status {} is not supported yet"
                                 .format(status))
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


def start_workflow(organization, workflow):
    """Start a workflow."""
    workflow.status = WorkflowStatus.running
    db.session.commit()
    if workflow.type_ == 'yadage':
        return run_yadage_workflow_from_spec(organization,
                                             workflow)
    elif workflow.type_ == 'cwl':
        return run_cwl_workflow_from_spec_endpoint(organization,
                                                   workflow)


def run_yadage_workflow_from_spec(organization, workflow):
    """Run a yadage workflow."""
    try:
        # Remove organization from workspace path since workflow
        # engines already work in its organization folder.
        workspace_path_without_organization = \
            '/'.join(workflow.workspace_path.strip('/').split('/')[1:])
        kwargs = {
            "workflow_uuid": str(workflow.id_),
            "workflow_workspace": workspace_path_without_organization,
            "workflow_json": workflow.specification,
            "parameters": workflow.parameters
        }
        queue = organization_to_queue[organization]
        if not os.environ.get("TESTS"):
            resultobject = run_yadage_workflow.apply_async(
                kwargs=kwargs,
                queue='yadage-{}'.format(queue)
            )
        return jsonify({'message': 'Workflow successfully launched',
                        'workflow_id': workflow.id_,
                        'status': workflow.status.name,
                        'organization': organization,
                        'user': str(workflow.owner_id)}), 200

    except(KeyError, ValueError):
        traceback.print_exc()
        abort(400)


def run_cwl_workflow_from_spec_endpoint(organization, workflow):  # noqa
    """Run a CWL workflow."""
    try:
        kwargs = {
            "workflow_uuid": str(workflow.id_),
            "workflow_workspace": workflow.workspace_path,
            "workflow_json": workflow.specification,
            "parameters": workflow.parameters['input']
        }
        queue = organization_to_queue[organization]
        if not os.environ.get("TESTS"):
            resultobject = run_cwl_workflow.apply_async(
                kwargs=kwargs,
                queue='cwl-{}'.format(queue)
            )
        return jsonify({'message': 'Workflow successfully launched',
                        'workflow_id': str(workflow.id_),
                        'status': workflow.status.name,
                        'organization': organization,
                        'user': str(workflow.owner_id)}), 200

    except (KeyError, ValueError) as e:
        print(e)
        # traceback.print_exc()
        abort(400)
