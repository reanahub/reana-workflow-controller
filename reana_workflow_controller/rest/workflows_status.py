# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller status REST API."""

import json

from flask import Blueprint, jsonify, request

from reana_db.utils import _get_workflow_with_uuid_or_name

from reana_workflow_controller.config import WORKFLOW_TIME_FORMAT
from reana_workflow_controller.errors import (REANAExternalCallError,
                                              REANAWorkflowControllerError)
from reana_workflow_controller.rest.utils import (build_workflow_logs,
                                                  delete_workflow,
                                                  get_current_job_progress,
                                                  get_workflow_name,
                                                  start_workflow,
                                                  stop_workflow)

START = 'start'
STOP = 'stop'
DELETED = 'deleted'
STATUSES = {START, STOP, DELETED}

blueprint = Blueprint('statuses', __name__)


@blueprint.route('/workflows/<workflow_id_or_name>/logs', methods=['GET'])
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
                         'job_logs': build_workflow_logs(workflow),
                         'engine_specific': workflow.engine_specific}
        return jsonify({'workflow_id': workflow.id_,
                        'workflow_name': get_workflow_name(workflow),
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


@blueprint.route('/workflows/<workflow_id_or_name>/status', methods=['GET'])
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
        workflow_logs = build_workflow_logs(workflow)
        if not str(workflow.owner_id) == user_uuid:
            return jsonify(
                {'message': 'User {} is not allowed to access workflow {}'
                 .format(user_uuid, workflow_id_or_name)}), 403

        current_job_progress = get_current_job_progress(workflow.id_)
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
                        'name': get_workflow_name(workflow),
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


@blueprint.route('/workflows/<workflow_id_or_name>/status', methods=['PUT'])
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
        502:
          description: >-
            Request failed. Connection to a third party system has failed.
          examples:
            application/json:
              {
                "message": "Connection to database timed out, please retry."
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
            start_workflow(workflow, parameters)
            return jsonify({'message': 'Workflow successfully launched',
                            'workflow_id': str(workflow.id_),
                            'workflow_name': get_workflow_name(workflow),
                            'status': workflow.status.name,
                            'user': str(workflow.owner_id)}), 200
        elif status == DELETED:
            all_runs = True if request.json.get('all_runs') else False
            hard_delete = True if request.json.get('hard_delete') else False
            workspace = True if hard_delete or request.json.get('workspace') \
                else False
            return delete_workflow(workflow, all_runs, hard_delete, workspace)
        if status == STOP:
            stop_workflow(workflow)
            return jsonify({'message': 'Workflow successfully stopped',
                            'workflow_id': workflow.id_,
                            'workflow_name': get_workflow_name(workflow),
                            'status': workflow.status.name,
                            'user': str(workflow.owner_id)}), 200
        else:
            raise NotImplementedError("Status {} is not supported yet"
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
    except REANAExternalCallError as e:
        return jsonify({"message": str(e)}), 502
    except Exception as e:
        return jsonify({"message": str(e)}), 500
