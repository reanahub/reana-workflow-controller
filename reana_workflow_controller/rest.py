# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller REST API."""

import difflib
import json
import os
import pprint
import subprocess
import traceback
from datetime import datetime
from uuid import UUID, uuid4

import fs
from flask import (Blueprint, abort, current_app, jsonify, request,
                   send_from_directory)
from fs.errors import CreateFailed
from werkzeug.exceptions import NotFound

from reana_db.database import Session
from reana_db.models import Job, User, Workflow, WorkflowStatus
from reana_workflow_controller.config import (DEFAULT_NAME_FOR_WORKFLOWS,
                                              WORKFLOW_QUEUES,
                                              WORKFLOW_TIME_FORMAT)
from reana_workflow_controller.errors import (REANAWorkflowControllerError,
                                              UploadPathError,
                                              WorkflowDeletionError,
                                              WorkflowInexistentError,
                                              WorkflowNameError)
from reana_workflow_controller.tasks import (run_cwl_workflow,
                                             run_serial_workflow,
                                             run_yadage_workflow,
                                             stop_workflow)
from reana_workflow_controller.utils import (create_workflow_workspace,
                                             list_directory_files,
                                             remove_files_recursive_wildcard,
                                             remove_workflow_jobs_from_cache,
                                             remove_workflow_workspace)
from reana_workflow_controller.workflow_run_managers.kubernetes import \
    KubernetesWorkflowRunManager

START = 'start'
STOP = 'stop'
DELETED = 'deleted'
STATUSES = {START, STOP, DELETED}

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
          examples:
            application/json:
              [
                {
                  "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                  "name": "mytest-1",
                  "status": "running",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                },
                {
                  "id": "3c9b117c-d40a-49e3-a6de-5f89fcada5a3",
                  "name": "mytest-2",
                  "status": "finished",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                },
                {
                  "id": "72e3ee4f-9cd3-4dc7-906c-24511d9f5ee3",
                  "name": "mytest-3",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                },
                {
                  "id": "c4c0a1a6-beef-46c7-be04-bf4b3beca5a1",
                  "name": "mytest-4",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
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
              operational_options:
                type: object
                description: Operational options.
              reana_specification:
                type: object
                description: >-
                  Workflow specification in JSON format.
              workflow_name:
                type: string
                description: Workflow name. If empty name will be generated.
            required: [reana_specification,
                       workflow_name,
                       operational_options]
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
        workflow_name = request.json.get('workflow_name', '')
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
                            reana_specification=request.json[
                                'reana_specification'],
                            operational_options=request.json.get(
                                'operational_options'),
                            type_=request.json[
                                'reana_specification']['workflow']['type'],
                            logs='')
        Session.add(workflow)
        Session.object_session(workflow).commit()
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


@restapi_blueprint.route(
    '/workflows/<workflow_id_or_name>/workspace/<path:file_name>',
    methods=['DELETE'])
def delete_file(workflow_id_or_name, file_name):  # noqa
    r"""Delete a file from the workspace.

    ---
    delete:
      summary: Delete the specified file.
      description: >-
        This resource is expecting a workflow UUID and a filename existing
        inside the workspace to be deleted.
      operationId: delete_file
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
          description: Required. Workflow UUID or name
          required: true
          type: string
        - name: file_name
          in: path
          description: Required. Name (or path) of the file to be deleted.
          required: true
          type: string
      responses:
        200:
          description: >-
            Requests succeeded. The file has been downloaded.
          schema:
            type: file
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
        abs_path_to_workspace = os.path.join(
            current_app.config['SHARED_VOLUME_PATH'], workflow.get_workspace())
        deleted = remove_files_recursive_wildcard(
          abs_path_to_workspace, file_name)

        return jsonify(deleted), 200

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
    except OSError as e:
        return jsonify(
            {"message": "Error while deleting {}.".format(file_name)}), 500
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
    except CreateFailed:
        return jsonify({"message": "Workspace does not exist."}), 404
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
          enum:
            - start
            - stop
            - deleted
        - name: parameters
          in: body
          description: >-
            Optional. Additional input parameters and operational options for
            workflow execution. Possible parameters are `CACHE=on/off`, passed
            to disable caching of results in serial workflows,
            `all_runs=True/False` deletes all runs of a given workflow
            if status is set to deleted, `workspace=True/False` which deletes
            the workspace of a workflow and finally `hard_delete=True` which
            removes completely the workflow data from the database and the
            workspace from the shared filesystem.
          required: false
          schema:
            type: object
            properties:
              CACHE:
                type: string
              all_runs:
                type: boolean
              workspace:
                type: boolean
              hard_delete:
                type: boolean
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
        parameters = {}
        if request.json:
            parameters = request.json
        if status == START:
            _start_workflow(workflow, parameters)
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': str(workflow.id_),
                            'workflow_name': _get_workflow_name(workflow),
                            'status': workflow.status.name,
                            'user': str(workflow.owner_id)}), 200
        elif status == DELETED:
            all_runs = True if request.json.get('all_runs') else False
            hard_delete = True if request.json.get('hard_delete') else False
            workspace = True if hard_delete or request.json.get('workspace') \
                else False
            return _delete_workflow(workflow, all_runs, hard_delete, workspace)
        if status == STOP:
            _stop_workflow(workflow)
            return jsonify({'message': 'Workflow successfully stopped',
                            'workflow_id': workflow.id_,
                            'workflow_name': _get_workflow_name(workflow),
                            'status': workflow.status.name,
                            'user': str(workflow.owner_id)}), 200
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


@restapi_blueprint.route('/workflows/<workflow_id_or_name>/parameters',
                         methods=['GET'])
def get_workflow_parameters(workflow_id_or_name):  # noqa
    r"""Get workflow input parameters.

    ---
    get:
      summary: Get workflow parameters.
      description: >-
        This resource reports the input parameters of workflow.
      operationId: get_workflow_parameters
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
            Request succeeded. Workflow input parameters, including the status
            are returned.
          schema:
            type: object
            properties:
              id:
                type: string
              name:
                type: string
              type:
                type: string
              parameters:
                type: object
          examples:
            application/json:
              {
                'id': 'dd4e93cf-e6d0-4714-a601-301ed97eec60',
                'name': 'workflow.24',
                'type': 'serial',
                'parameters': {'helloworld': 'code/helloworld.py',
                               'inputfile': 'data/names.txt',
                               'outputfile': 'results/greetings.txt',
                               'sleeptime': 2}
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
        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id_or_name)}), 403

        workflow_parameters = workflow.get_input_parameters()
        return jsonify({
            'id': workflow.id_,
            'name': _get_workflow_name(workflow),
            'type': workflow.reana_specification['workflow']['type'],
            'parameters': workflow_parameters}), 200
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


@restapi_blueprint.route('/workflows/<workflow_id_or_name_a>/diff/'
                         '<workflow_id_or_name_b>', methods=['GET'])
def get_workflow_diff(workflow_id_or_name_a, workflow_id_or_name_b):  # noqa
    r"""Get differences between two workflows.

    ---
    get:
      summary: Get diff between two workflows.
      description: >-
        This resource shows the differences between
        the assets of two workflows.
        Resource is expecting two workflow UUIDs or names.
      operationId: get_workflow_diff
      produces:
        - application/json
      parameters:
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_id_or_name_a
          in: path
          description: Required. Analysis UUID or name of the first workflow.
          required: true
          type: string
        - name: workflow_id_or_name_b
          in: path
          description: Required. Analysis UUID or name of the second workflow.
          required: true
          type: string
        - name: brief
          in: query
          description: Optional flag. If set, file contents are examined.
          required: false
          type: boolean
          default: false
        - name: context_lines
          in: query
          description: Optional parameter. Sets number of context lines
                       for workspace diff output.
          required: false
          type: string
          default: '5'
      responses:
        200:
          description: >-
            Request succeeded. Info about a workflow, including the status is
            returned.
          schema:
            type: object
            properties:
              reana_specification:
                type: string
              workspace_listing:
                type: string
          examples:
            application/json:
              {
                "reana_specification":
                ["- nevents: 100000\n+ nevents: 200000"],
                "workspace_listing": {"Only in workspace a: code"}
              }
        400:
          description: >-
            Request failed. The incoming payload seems malformed.
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
            Request failed. Either user or workflow does not exist.
          examples:
            application/json:
              {
                "message": "Workflow 256b25f4-4cfb-4684-b7a8-73872ef455a1 does
                            not exist."
              }
        500:
          description: >-
            Request failed. Internal controller error.
    """
    try:
        user_uuid = request.args['user']
        brief = request.args.get('brief', False)
        brief = True if brief == 'true' else False
        context_lines = request.args.get('context_lines', 5)

        workflow_a_exists = False
        workflow_a = _get_workflow_with_uuid_or_name(workflow_id_or_name_a,
                                                     user_uuid)
        workflow_a_exists = True
        workflow_b = _get_workflow_with_uuid_or_name(workflow_id_or_name_b,
                                                     user_uuid)
        if not workflow_id_or_name_a or not workflow_id_or_name_b:
            raise ValueError("Workflow id or name is not supplied")
        specification_diff = get_specification_diff(
            workflow_a, workflow_b)

        try:
            workspace_diff = get_workspace_diff(
                workflow_a, workflow_b, brief, context_lines)
        except ValueError as e:
            workspace_diff = str(e)

        response = {'reana_specification': json.dumps(specification_diff),
                    'workspace_listing': json.dumps(workspace_diff)}
        return jsonify(response)
    except REANAWorkflowControllerError as e:
        return jsonify({"message": str(e)}), 409
    except WorkflowInexistentError as e:
        wrong_workflow = workflow_id_or_name_b if workflow_a_exists \
            else workflow_id_or_name_a
        return jsonify({'message': 'Workflow {0} does not exist.'.
                                   format(wrong_workflow)}), 404
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


def _start_workflow(workflow, parameters):
    """Start a workflow."""
    if workflow.status == WorkflowStatus.created:
        workflow.run_started_at = datetime.now()
        workflow.status = WorkflowStatus.running
        if parameters:
            workflow.input_parameters = parameters.get('input_parameters')
            workflow.operational_options = \
                parameters.get('operational_options')
        current_db_sessions = Session.object_session(workflow)
        current_db_sessions.add(workflow)
        current_db_sessions.commit()
        kwrm = KubernetesWorkflowRunManager(workflow)
        kwrm.start_batch_workflow_run()
    else:
        verb = "is" if workflow.status == WorkflowStatus.running else "has"
        message = \
            ("Workflow {id_} could not be started because it {verb}"
             " already {status}.").format(id_=workflow.id_, verb=verb,
                                          status=str(workflow.status.name))
        raise REANAWorkflowControllerError(message)


def _stop_workflow(workflow):
    """Stop a given workflow."""
    if workflow.status == WorkflowStatus.running:
        workflow.run_stopped_at = datetime.now()
        workflow.status = WorkflowStatus.stopped
        current_db_sessions = Session.object_session(workflow)
        current_db_sessions.add(workflow)
        current_db_sessions.commit()
        kwargs = {
            'workflow_uuid': str(workflow.id_),
            'job_list':
            workflow.job_progress.get('running', {}).get('job_ids', []),
        }
        if workflow.type_ in ['serial', 'yadage', 'cwl']:
            stop_workflow.apply_async(
                kwargs=kwargs,
                queue=WORKFLOW_QUEUES[workflow.type_],
                task_id='delete-{}'.format(str(workflow.id_))
            )
        else:
            raise NotImplementedError(
                'Workflow type {} does not support '
                'stop yet.'.format(workflow.type_))
    else:
        message = \
            ("Workflow {id_} is not running.").format(id_=workflow.id_)
        raise REANAWorkflowControllerError(message)


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


def _get_workflow_input_parameters(workflow):
    """Return workflow input parameters merged with live ones, if given."""
    if workflow.input_parameters:
        return dict(workflow.get_input_parameters(),
                    **workflow.input_parameters)
    else:
        return workflow.get_input_parameters()


def _delete_workflow(workflow,
                     all_runs=False,
                     hard_delete=False,
                     workspace=False):
    """Delete workflow."""
    if workflow.status in [WorkflowStatus.created,
                           WorkflowStatus.finished,
                           WorkflowStatus.stopped,
                           WorkflowStatus.deleted,
                           WorkflowStatus.failed]:
        to_be_deleted = [workflow]
        if all_runs:
            to_be_deleted += Session.query(Workflow).\
                filter(Workflow.name == workflow.name,
                       Workflow.status != WorkflowStatus.running).all()
        for workflow in to_be_deleted:
            if hard_delete:
                remove_workflow_workspace(workflow.get_workspace())
                _delete_workflow_row_from_db(workflow)
            else:
                if workspace:
                    remove_workflow_workspace(workflow.get_workspace())
                _mark_workflow_as_deleted_in_db(workflow)
            remove_workflow_jobs_from_cache(workflow)

        return jsonify({'message': 'Workflow successfully deleted',
                        'workflow_id': workflow.id_,
                        'workflow_name': _get_workflow_name(workflow),
                        'status': workflow.status.name,
                        'user': str(workflow.owner_id)}), 200
    elif workflow.status == WorkflowStatus.running:
        raise WorkflowDeletionError(
            'Workflow {0}.{1} cannot be deleted as it'
            ' is currently running.'.
            format(
                workflow.name,
                workflow.run_number))


def _delete_workflow_row_from_db(workflow):
    """Remove workflow row from database."""
    Session.query(Workflow).filter_by(id_=workflow.id_).delete()
    Session.commit()


def _mark_workflow_as_deleted_in_db(workflow):
    """Mark workflow as deleted."""
    workflow.status = WorkflowStatus.deleted
    current_db_sessions = Session.object_session(workflow)
    current_db_sessions.add(workflow)
    current_db_sessions.commit()


def get_specification_diff(workflow_a, workflow_b, output_format='unified'):
    """Return differences between two workflow specifications.

    :param workflow_a: The first workflow to be compared.
    :type: reana_db.models.Workflow instance.
    :param workflow_a: The first workflow to be compared.
    :type: `~reana_db.models.Workflow` instance.
    :param output_format: Sets output format. Optional.
    :type: String. One of ['unified', 'context', 'html'].
           Unified format returned if not set.

    :rtype: List with lines of differences.
    """
    if output_format not in ['unified', 'context', 'html']:
        raise ValueError('Unknown output format.'
                         'Please select one of unified, context or html.')

    if output_format == 'unified':
        diff_method = getattr(difflib, 'unified_diff')
    elif output_format == 'context':
        diff_method = getattr(difflib, 'context_diff')
    elif output_format == 'html':
        diff_method = getattr(difflib, 'HtmlDiff')

    specification_diff = dict.fromkeys(workflow_a.reana_specification.keys())
    for section in specification_diff:
        section_a = pprint.pformat(
            workflow_a.reana_specification.get(section, '')).\
            splitlines()
        section_b = pprint.pformat(
            workflow_b.reana_specification.get(section, '')).\
            splitlines()
        # skip first 2 lines of diff relevant if input comes from files
        specification_diff[section] = list(diff_method(section_a,
                                                       section_b))[2:]
    return specification_diff


def get_workspace_diff(workflow_a, workflow_b, brief=False, context_lines=5):
    """Return differences between two workspaces.

    :param workflow_a: The first workflow to be compared.
    :type: reana_db.models.Workflow instance.
    :param workflow_b: The second workflow to be compared.
    :type: reana_db.models.Workflow instance.
    :param brief: Optional flag to show brief workspace diff.
    :type: Boolean.
    :param context_lines: The number of context lines to show above and after
                          the discovered differences.
    :type: Integer or string.

    :rtype: Dictionary with file paths and their sizes
            unique to each workspace.
    """
    workspace_a = workflow_a.get_workspace()
    workspace_b = workflow_b.get_workspace()
    reana_fs = fs.open_fs(current_app.config['SHARED_VOLUME_PATH'])
    if reana_fs.exists(workspace_a) and reana_fs.exists(workspace_b):
        diff_command = ['diff',
                        '--unified={}'.format(context_lines),
                        '-r',
                        reana_fs.getospath(workspace_a),
                        reana_fs.getospath(workspace_b)]
        if brief:
            diff_command.append('-q')
        diff_result = subprocess.run(diff_command,
                                     stdout=subprocess.PIPE)
        diff_result_string = diff_result.stdout.decode('utf-8')
        diff_result_string = diff_result_string.replace(
            reana_fs.getospath(workspace_a).decode('utf-8'),
            _get_workflow_name(workflow_a))
        diff_result_string = diff_result_string.replace(
            reana_fs.getospath(workspace_b).decode('utf-8'),
            _get_workflow_name(workflow_b))

        return diff_result_string
    else:
        if not reana_fs.exists(workspace_a):
            raise ValueError('Workspace of {} does not exist.'.format(
                _get_workflow_name(workflow_a)))
        if not reana_fs.exists(workspace_b):
            raise ValueError('Workspace of {} does not exist.'.format(
                _get_workflow_name(workflow_b)))
