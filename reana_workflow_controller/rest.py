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
from reana_commons.utils import (get_workflow_status_change_verb,
                                 get_workspace_disk_usage)
from reana_db.database import Session
from reana_db.models import Job, User, Workflow, WorkflowStatus
from reana_db.utils import _get_workflow_with_uuid_or_name
from werkzeug.exceptions import NotFound

from reana_workflow_controller.config import (
    DEFAULT_INTERACTIVE_SESSION_IMAGE,
    DEFAULT_INTERACTIVE_SESSION_PORT,
    DEFAULT_NAME_FOR_WORKFLOWS,
    SHARED_VOLUME_PATH,
    WORKFLOW_QUEUES,
    WORKFLOW_TIME_FORMAT)
from reana_workflow_controller.errors import (REANAUploadPathError,
                                              REANAWorkflowControllerError,
                                              REANAWorkflowDeletionError,
                                              REANAWorkflowNameError)
from reana_workflow_controller.utils import (create_workflow_workspace,
                                             list_directory_files,
                                             remove_files_recursive_wildcard,
                                             remove_workflow_jobs_from_cache,
                                             remove_workflow_workspace)
from reana_workflow_controller.workflow_run_manager import \
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
        - name: verbose
          in: query
          description: Optional flag to show more information.
          required: false
          type: boolean
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
                size:
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
                  "name": "mytest.1",
                  "status": "running",
                  "size": "10M",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                },
                {
                  "id": "3c9b117c-d40a-49e3-a6de-5f89fcada5a3",
                  "name": "mytest.2",
                  "status": "finished",
                  "size": "12M",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                },
                {
                  "id": "72e3ee4f-9cd3-4dc7-906c-24511d9f5ee3",
                  "name": "mytest.3",
                  "status": "created",
                  "size": "180K",
                  "user": "00000000-0000-0000-0000-000000000000",
                  "created": "2018-06-13T09:47:35.66097",
                },
                {
                  "id": "c4c0a1a6-beef-46c7-be04-bf4b3beca5a1",
                  "name": "mytest.4",
                  "status": "created",
                  "size": "1G",
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
        verbose = request.args.get('verbose', False)
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
                                 strftime(WORKFLOW_TIME_FORMAT),
                                 'size': '-'}
            if verbose:
                reana_fs = fs.open_fs(SHARED_VOLUME_PATH)
                if reana_fs.exists(workflow.get_workspace()):
                    absolute_workspace_path = reana_fs.getospath(
                        workflow.get_workspace())
                    disk_usage_info = get_workspace_disk_usage(
                        absolute_workspace_path)
                    if disk_usage_info:
                        workflow_response['size'] = disk_usage_info[-1]['size']
                    else:
                        workflow_response['size'] = '0K'
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
                raise REANAWorkflowNameError('Workflow name {} is not valid.'.
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

    except (REANAWorkflowNameError, KeyError) as e:
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
            raise REANAUploadPathError('Path cannot contain "..".')
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

    except ValueError:
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

    except ValueError:
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

    except ValueError:
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

    except ValueError:
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
                "logs": "{'workflow_logs': string,
                          'job_logs': {
                             '256b25f4-4cfb-4684-b7a8-73872ef455a2': string,
                             '256b25f4-4cfb-4684-b7a8-73872ef455a3': string,
                           },
                          'engine_specific': object,
                         }",
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
        workflow_logs = {'workflow_logs': workflow.logs,
                         'job_logs': _get_workflow_logs(workflow),
                         'engine_specific': workflow.engine_specific}
        return jsonify({'workflow_id': workflow.id_,
                        'workflow_name': _get_workflow_name(workflow),
                        'logs': json.dumps(workflow_logs),
                        'user': user_uuid}), 200

    except ValueError:
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
                        'logs': json.dumps(workflow_logs)}), 200
    except ValueError:
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
    except ValueError:
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


@restapi_blueprint.route('/workflows/<workflow_id_or_name>/open',
                         methods=['POST'])
def open_interactive_session(workflow_id_or_name):  # noqa
    r"""Start an interactive session inside the workflow workspace.

    ---
    post:
      summary: Start an interactive session inside the workflow workspace.
      description: >-
        This resource is expecting a workflow to start an interactive session
        within its workspace.
      operationId: open_interactive_session
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
        - name: workflow_id_or_name
          in: path
          description: Required. Workflow UUID or name.
          required: true
          type: string
        - name: interactive_environment
          in: body
          description: >-
            Optional. Image to use when spawning the interactive session along
            with the needed port.
          required: false
          schema:
            type: object
            properties:
              image:
                type: string
              port:
                type: integer
      responses:
        200:
          description: >-
            Request succeeded. The interactive session has been opened.
          schema:
            type: object
            properties:
              path:
                type: string
          examples:
            application/json:
              {
                "path": "/dd4e93cf-e6d0-4714-a601-301ed97eec60",
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
          examples:
            application/json:
              {
                "message": "Malformed request."
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
        if request.json and not request.json.get("image"):
            raise ValueError("If interactive_environment payload is sent, it˛"
                             "should contain the image property.")

        user_uuid = request.args["user"]
        image = request.json.get("image", DEFAULT_INTERACTIVE_SESSION_IMAGE)
        port = request.json.get("port", DEFAULT_INTERACTIVE_SESSION_PORT)
        workflow = None
        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name,
                                                   user_uuid)
        kwrm = KubernetesWorkflowRunManager(workflow)
        access_path = kwrm.start_interactive_session(image, port)
        return jsonify({"path": "{}".format(access_path)}), 200

    except (KeyError, ValueError) as e:
        status_code = 400 if workflow else 404
        return jsonify({"message": str(e)}), status_code
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
    except ValueError:
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
    except ValueError as e:
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


@restapi_blueprint.route('/workflows/move_files/<workflow_id_or_name>',
                         methods=['PUT'])
def move_files(workflow_id_or_name):  # noqa
    r"""Move files within workspace.
    ---
    put:
      summary: Move files within workspace.
      description: >-
        This resource moves files within the workspace. Resource is expecting
        a workflow UUID.
      operationId: move_files
      consumes:
        - application/json
      produces:
        - application/json
      parameters:
        - name: workflow_id_or_name
          in: path
          description: Required. Analysis UUID or name.
          required: true
          type: string
        - name: source
          in: query
          description: Required. Source file(s).
          required: true
          type: string
        - name: target
          in: query
          description: Required. Target file(s).
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner..
          required: true
          type: string
      responses:
        200:
          description: >-
            Request succeeded. Message about successfully moved files is
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
          examples:
            application/json:
              {
                "message": "Files were successfully moved",
                "workflow_id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                "workflow_name": "mytest.1",
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
            Request failed. Either User or Workflow does not exist.
          examples:
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
        source = request.args['source']
        target = request.args['target']
        if workflow.status == 'running':
            return jsonify({'message': 'Workflow is running, files can not be '
                            'moved'}), 400

        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id_or_name)}), 403

        _mv_files(source, target, workflow)
        message = 'File(s) {} were successfully moved'.format(source)

        return jsonify({
            'message': message,
            'workflow_id': workflow.id_,
            'workflow_name': _get_workflow_name(workflow)}), 200

    except ValueError:
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


def _mv_files(source, target, workflow):
    """Move files within workspace."""
    absolute_workspace_path = os.path.join(
        current_app.config['SHARED_VOLUME_PATH'],
        workflow.get_workspace())
    absolute_source_path = os.path.join(
        current_app.config['SHARED_VOLUME_PATH'],
        absolute_workspace_path,
        source
    )
    absolute_target_path = os.path.join(
        current_app.config['SHARED_VOLUME_PATH'],
        absolute_workspace_path,
        target
    )

    if not os.path.exists(absolute_source_path):
        message = 'Path {} does not exist'.format(source)
        raise REANAWorkflowControllerError(message)
    if not absolute_source_path.startswith(absolute_workspace_path):
        message = 'Source path is outside user workspace'
        raise REANAWorkflowControllerError(message)
    if not absolute_source_path.startswith(absolute_workspace_path):
        message = 'Target path is outside workspace'
        raise REANAWorkflowControllerError(message)
    try:
        reana_fs = fs.open_fs(absolute_workspace_path)
        source_info = reana_fs.getinfo(source)
        if source_info.is_dir:
            reana_fs.movedir(src_path=source,
                             dst_path=target,
                             create=True)
        else:
            reana_fs.move(src_path=source,
                          dst_path=target)
        reana_fs.close()
    except Exception as e:
        reana_fs.close()
        message = 'Something went wrong:\n {}'.format(e)
        raise REANAWorkflowControllerError(message)


def _start_workflow(workflow, parameters):
    """Start a workflow."""
    if workflow.status in [WorkflowStatus.created, WorkflowStatus.queued]:
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
        message = \
            ("Workflow {id_} could not be started because it {verb}"
             " already {status}.").format(
               id_=workflow.id_,
               verb=get_workflow_status_change_verb(workflow.status.name),
               status=str(workflow.status.name))
        raise REANAWorkflowControllerError(message)


def _stop_workflow(workflow):
    """Stop a given workflow."""
    if workflow.status == WorkflowStatus.running:
        kwrm = KubernetesWorkflowRunManager(workflow)
        job_list = workflow.job_progress.get('running', {}).get('job_ids', [])
        workflow.run_stopped_at = datetime.now()
        kwrm.stop_batch_workflow_run(job_list)
        workflow.status = WorkflowStatus.stopped
        current_db_sessions = Session.object_session(workflow)
        current_db_sessions.add(workflow)
        current_db_sessions.commit()
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


def _get_workflow_logs(workflow):
    """Return the logs for all jobs of a workflow."""
    jobs = Session.query(Job).filter_by(workflow_uuid=workflow.id_).order_by(
        Job.created).all()
    all_logs = {}
    for job in jobs:
        all_logs[str(job.id_)] = job.logs or ''
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
        raise REANAWorkflowDeletionError(
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
