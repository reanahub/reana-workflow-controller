# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller workflows REST API."""

import json
from uuid import uuid4

import fs
from flask import Blueprint, jsonify, request
from reana_commons.utils import get_workspace_disk_usage
from reana_db.database import Session
from reana_db.models import User, Workflow
from reana_db.utils import _get_workflow_with_uuid_or_name

from reana_workflow_controller.config import (
    DEFAULT_NAME_FOR_WORKFLOWS,
    SHARED_VOLUME_PATH,
    WORKFLOW_TIME_FORMAT,
)
from reana_workflow_controller.errors import (
    REANAWorkflowControllerError,
    REANAWorkflowNameError,
)
from reana_workflow_controller.rest.utils import (
    create_workflow_workspace,
    get_specification_diff,
    get_workflow_name,
    get_workflow_progress,
    get_workspace_diff,
    use_paginate_args,
)


START = "start"
STOP = "stop"
DELETED = "deleted"
STATUSES = {START, STOP, DELETED}

blueprint = Blueprint("workflows", __name__)


@blueprint.route("/workflows", methods=["GET"])
@use_paginate_args()
def get_workflows(paginate=None):  # noqa
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
        - name: type
          in: query
          description: Required. Type of workflows.
          required: true
          type: string
        - name: verbose
          in: query
          description: Optional flag to show more information.
          required: false
          type: boolean
        - name: block_size
          in: query
          description: Size format, either 'b' (bytes) or 'k' (kilobytes).
          required: false
          type: string
        - name: page
          in: query
          description: Results page number (pagination).
          required: false
          type: string
        - name: size
          in: query
          description: Number of results per page (pagination).
          required: false
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
                size:
                  type: string
                user:
                  type: string
                created:
                  type: string
                progress:
                  type: object
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
        user_uuid = request.args["user"]
        user = User.query.filter(User.id_ == user_uuid).first()
        type_ = request.args.get("type", "batch")
        verbose = json.loads(request.args.get("verbose", "false").lower())
        block_size = request.args.get("block_size")
        if not user:
            return jsonify({"message": "User {} does not exist".format(user_uuid)}), 404
        workflows = []
        pagination_dict = paginate(user.workflows)
        for workflow in pagination_dict["items"]:
            workflow_response = {
                "id": workflow.id_,
                "name": get_workflow_name(workflow),
                "status": workflow.status.name,
                "user": user_uuid,
                "created": workflow.created.strftime(WORKFLOW_TIME_FORMAT),
                "progress": get_workflow_progress(workflow),
                "size": "-",
            }
            if type_ == "interactive":
                if (
                    not workflow.interactive_session
                    or not workflow.interactive_session_name
                    or not workflow.interactive_session_type
                ):
                    continue
                workflow_response["session_type"] = workflow.interactive_session_type
                workflow_response["session_uri"] = workflow.interactive_session
            if verbose:
                reana_fs = fs.open_fs(SHARED_VOLUME_PATH)
                if reana_fs.exists(workflow.workspace_path):
                    absolute_workspace_path = reana_fs.getospath(
                        workflow.workspace_path
                    )
                    disk_usage_info = get_workspace_disk_usage(
                        absolute_workspace_path, block_size=block_size
                    )
                    if disk_usage_info:
                        workflow_response["size"] = disk_usage_info[-1]["size"]
                    else:
                        workflow_response["size"] = "0K"
            workflows.append(workflow_response)

        return jsonify(workflows), 200
    except ValueError:
        return jsonify({"message": "Malformed request."}), 400
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except json.JSONDecodeError:
        return jsonify({"message": "Your request contains not valid JSON."}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route("/workflows", methods=["POST"])
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
              git_data:
                type: object
                description: >-
                  GitLab data.
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
        user_uuid = request.args["user"]
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return (
                jsonify(
                    {"message": "User with id:{} does not exist".format(user_uuid)}
                ),
                404,
            )
        workflow_uuid = str(uuid4())
        # Use name prefix user specified or use default name prefix
        # Actual name is prefix + autoincremented run_number.
        workflow_name = request.json.get("workflow_name", "")
        if workflow_name == "":
            workflow_name = DEFAULT_NAME_FOR_WORKFLOWS
        else:
            try:
                workflow_name.encode("ascii")
            except UnicodeEncodeError:
                # `workflow_name` contains something else than just ASCII.
                raise REANAWorkflowNameError(
                    "Workflow name {} is not valid.".format(workflow_name)
                )
        git_ref = ""
        git_repo = ""
        if "git_data" in request.json:
            git_data = request.json["git_data"]
            git_ref = git_data["git_commit_sha"]
            git_repo = git_data["git_url"]
        # add spec and params to DB as JSON
        workflow = Workflow(
            id_=workflow_uuid,
            name=workflow_name,
            owner_id=request.args["user"],
            reana_specification=request.json["reana_specification"],
            operational_options=request.json.get("operational_options", {}),
            type_=request.json["reana_specification"]["workflow"]["type"],
            logs="",
            git_ref=git_ref,
            git_repo=git_repo,
        )
        Session.add(workflow)
        Session.object_session(workflow).commit()
        if git_ref:
            create_workflow_workspace(
                workflow.workspace_path,
                user_id=user.id_,
                git_url=git_data["git_url"],
                git_branch=git_data["git_branch"],
                git_ref=git_ref,
            )
        else:
            create_workflow_workspace(workflow.workspace_path)
        return (
            jsonify(
                {
                    "message": "Workflow workspace created",
                    "workflow_id": workflow.id_,
                    "workflow_name": get_workflow_name(workflow),
                }
            ),
            201,
        )

    except (REANAWorkflowNameError, KeyError) as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route("/workflows/<workflow_id_or_name>/parameters", methods=["GET"])
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
        user_uuid = request.args["user"]
        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name, user_uuid)
        if not str(workflow.owner_id) == user_uuid:
            return (
                jsonify(
                    {
                        "message": "User {} is not allowed to access workflow {}".format(
                            user_uuid, workflow_id_or_name
                        )
                    }
                ),
                403,
            )

        workflow_parameters = workflow.get_input_parameters()
        return (
            jsonify(
                {
                    "id": workflow.id_,
                    "name": get_workflow_name(workflow),
                    "type": workflow.reana_specification["workflow"]["type"],
                    "parameters": workflow_parameters,
                }
            ),
            200,
        )
    except ValueError:
        return (
            jsonify(
                {
                    "message": "REANA_WORKON is set to {0}, but "
                    "that workflow does not exist. "
                    "Please set your REANA_WORKON environment "
                    "variable appropriately.".format(workflow_id_or_name)
                }
            ),
            404,
        )
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route(
    "/workflows/<workflow_id_or_name_a>/diff/" "<workflow_id_or_name_b>",
    methods=["GET"],
)
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
        user_uuid = request.args["user"]
        brief = json.loads(request.args.get("brief", "false").lower())
        context_lines = request.args.get("context_lines", 5)

        workflow_a_exists = False
        workflow_a = _get_workflow_with_uuid_or_name(workflow_id_or_name_a, user_uuid)
        workflow_a_exists = True
        workflow_b = _get_workflow_with_uuid_or_name(workflow_id_or_name_b, user_uuid)
        if not workflow_id_or_name_a or not workflow_id_or_name_b:
            raise ValueError("Workflow id or name is not supplied")
        specification_diff = get_specification_diff(workflow_a, workflow_b)

        try:
            workspace_diff = get_workspace_diff(
                workflow_a, workflow_b, brief, context_lines
            )
        except ValueError as e:
            workspace_diff = str(e)

        response = {
            "reana_specification": json.dumps(specification_diff),
            "workspace_listing": json.dumps(workspace_diff),
        }
        return jsonify(response)
    except REANAWorkflowControllerError as e:
        return jsonify({"message": str(e)}), 409
    except ValueError as e:
        wrong_workflow = (
            workflow_id_or_name_b if workflow_a_exists else workflow_id_or_name_a
        )
        return (
            jsonify({"message": "Workflow {0} does not exist.".format(wrong_workflow)}),
            404,
        )
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    except json.JSONDecodeError:
        return jsonify({"message": "Your request contains not valid JSON."}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500
