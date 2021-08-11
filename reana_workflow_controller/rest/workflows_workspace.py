# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller workspaces REST API."""

import json
import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
)
from fs.errors import CreateFailed
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import NotFound

from reana_db.models import User
from reana_db.utils import (
    _get_workflow_with_uuid_or_name,
    store_workflow_disk_quota,
    update_users_disk_quota,
)
from reana_workflow_controller.errors import (
    REANAUploadPathError,
    REANAWorkflowControllerError,
)
from reana_workflow_controller.rest.utils import (
    get_workflow_name,
    list_directory_files,
    download_files_recursive_wildcard,
    list_files_recursive_wildcard,
    remove_files_recursive_wildcard,
    use_paginate_args,
)
from reana_workflow_controller.rest.utils import mv_files

blueprint = Blueprint("workspaces", __name__)


@blueprint.route("/workflows/<workflow_id_or_name>/workspace", methods=["POST"])
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
        - application/octet-stream
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
        - name: file
          in: body
          description: Required. File to add to the workspace.
          required: true
          schema:
            type: string
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
        if not ("application/octet-stream" in request.headers.get("Content-Type")):
            return (
                jsonify(
                    {
                        "message": f"Wrong Content-Type "
                        f'{request.headers.get("Content-Type")} '
                        f"use application/octet-stream"
                    }
                ),
                400,
            )
        user_uuid = request.args["user"]
        full_file_name = request.args["file_name"]
        if not full_file_name:
            raise ValueError("The file transferred needs to have name.")

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name, user_uuid)

        filename = full_file_name.split("/")[-1]

        # Remove starting '/' in path
        if full_file_name[0] == "/":
            full_file_name = full_file_name[1:]
        elif ".." in full_file_name.split("/"):
            raise REANAUploadPathError('Path cannot contain "..".')
        absolute_workspace_path = workflow.workspace_path
        if len(full_file_name.split("/")) > 1:
            dirs = full_file_name.split("/")[:-1]
            absolute_workspace_path = os.path.join(
                workflow.workspace_path, "/".join(dirs)
            )
            if not os.path.exists(absolute_workspace_path):
                os.makedirs(absolute_workspace_path)
        absolute_file_path = os.path.join(absolute_workspace_path, filename)

        FileStorage(request.stream).save(absolute_file_path, buffer_size=32768)
        # update user and workflow resource disk quota
        store_workflow_disk_quota(workflow, bytes_to_sum=request.content_length)
        update_users_disk_quota(workflow.owner, bytes_to_sum=request.content_length)
        return (
            jsonify(
                {"message": "{} has been successfully uploaded.".format(full_file_name)}
            ),
            200,
        )

    except ValueError:
        return (
            jsonify(
                {
                    "message": "REANA_WORKON is set to {0}, but "
                    "that workflow does not exist. "
                    "Please set your REANA_WORKON environment"
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
    "/workflows/<workflow_id_or_name>/workspace/<path:file_name>", methods=["GET"]
)
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
        - name: preview
          in: query
          description: >-
            Optional flag to return a previewable response of the file
            (corresponding mime-type).
          required: false
          type: boolean
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
        user_uuid = request.args["user"]
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify({"message": "User {} does not exist".format(user)}), 404

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name, user_uuid)
        workflow_name = workflow.get_full_workflow_name()

        return download_files_recursive_wildcard(
            workflow_name, workflow.workspace_path, file_name
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
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except NotFound:
        return jsonify({"message": "{0} does not exist.".format(file_name)}), 404
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route(
    "/workflows/<workflow_id_or_name>/workspace/<path:file_name>", methods=["DELETE"]
)
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
        user_uuid = request.args["user"]
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify({"message": "User {} does not exist".format(user)}), 404

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name, user_uuid)
        deleted = remove_files_recursive_wildcard(workflow.workspace_path, file_name)
        # update user and workflow resource disk quota
        freed_up_bytes = sum(
            size.get("size", 0) for size in deleted["deleted"].values()
        )
        store_workflow_disk_quota(workflow, bytes_to_sum=-freed_up_bytes)
        update_users_disk_quota(user, bytes_to_sum=-freed_up_bytes)
        return jsonify(deleted), 200

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
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except NotFound:
        return jsonify({"message": "{0} does not exist.".format(file_name)}), 404
    except OSError:
        return jsonify({"message": "Error while deleting {}.".format(file_name)}), 500
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route("/workflows/<workflow_id_or_name>/workspace", methods=["GET"])
@use_paginate_args()
def get_files(workflow_id_or_name, paginate=None):  # noqa
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
        - name: file_name
          in: query
          description: File name(s) (glob) to list.
          required: false
          type: string
        - name: page
          in: query
          description: Results page number (pagination).
          required: false
          type: integer
        - name: size
          in: query
          description: Number of results per page (pagination).
          required: false
          type: integer
        - name: search
          in: query
          description: Filter workflow workspace files.
          required: false
          type: string
      responses:
        200:
          description: >-
            Requests succeeded. The list of code|input|output files has been
            retrieved.
          schema:
            type: object
            properties:
              total:
                type: integer
              items:
                type: array
                items:
                  type: object
                  properties:
                    name:
                      type: string
                    last-modified:
                      type: string
                    size:
                      type: object
                      properties:
                        raw:
                          type: number
                        human_readable:
                          type: string
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
        user_uuid = request.args["user"]
        search = request.args.get("search", None)
        user = User.query.filter(User.id_ == user_uuid).first()
        if not user:
            return jsonify({"message": "User {} does not exist".format(user)}), 404

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name, user_uuid)
        file_name = request.args.get("file_name")
        if search:
            search = json.loads(search)
        if file_name:
            file_list = list_files_recursive_wildcard(
                workflow.workspace_path, file_name, search=search
            )
        else:
            file_list = list_directory_files(workflow.workspace_path, search=search)
        pagination_dict = paginate(file_list)
        return jsonify(pagination_dict), 200

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
    except KeyError:
        return jsonify({"message": "Malformed request."}), 400
    except CreateFailed:
        return jsonify({"message": "Workspace does not exist."}), 404
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route("/workflows/move_files/<workflow_id_or_name>", methods=["PUT"])
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
        user_uuid = request.args["user"]
        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name, user_uuid)
        source = request.args["source"]
        target = request.args["target"]
        if workflow.status == "running":
            return (
                jsonify({"message": "Workflow is running, files can not be " "moved"}),
                400,
            )

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

        mv_files(source, target, workflow)
        message = "File(s) {} were successfully moved".format(source)

        return (
            jsonify(
                {
                    "message": message,
                    "workflow_id": workflow.id_,
                    "workflow_name": get_workflow_name(workflow),
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
    except REANAWorkflowControllerError as e:
        return jsonify({"message": str(e)}), 409
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except NotImplementedError as e:
        return jsonify({"message": str(e)}), 501
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route("/workflows/<workflow_id_or_name>/disk_usage", methods=["GET"])
def get_workflow_disk_usage(workflow_id_or_name):  # noqa
    r"""Get workflow disk usage.

    ---
    get:
      summary: Get disk usage of a workflow.
      description: >-
        This resource reports the disk usage of a workflow.
        Resource is expecting a workflow UUID and some parameters .
      operationId: get_workflow_disk_usage
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
        - name: user
          in: query
          description: Required. UUID of owner of the workflow.
          required: true
          type: string
        - name: parameters
          in: body
          description: >-
            Optional. Additional input parameters and operational options.
          required: false
          schema:
            type: object
      responses:
        200:
          description: >-
            Request succeeded. Info about the disk usage is
            returned.
          schema:
            type: object
            properties:
              workflow_id:
                type: string
              workflow_name:
                type: string
              user:
                type: string
              disk_usage_info:
                type: array
                items:
                  type: object
                  properties:
                    name:
                      type: string
                    size:
                      type: object
                      properties:
                        raw:
                          type: number
                        human_readable:
                          type: string
          examples:
            application/json:
              {
                "workflow_id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                "workflow_name": "mytest.1",
                "disk_usage_info": [{'name': 'file1.txt',
                                      'size': {
                                        'raw': 12580000,
                                        'human_readable': '12 MB'
                                       }
                                    },
                                    {'name': 'plot.png',
                                     'size': {
                                       'raw': 184320,
                                       'human_readable': '100 KB'
                                      }
                                    }]
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
            Request failed. User does not exist.
          examples:
            application/json:
              {
                "message": "Workflow cdcf48b1-c2f3-4693-8230-b066e088c6ac does
                            not exist"
              }
        500:
          description: >-
            Request failed. Internal controller error.
    """
    try:
        parameters = request.json or {}
        if not workflow_id_or_name:
            raise ValueError("workflow_id_or_name is not supplied")
        user_uuid = request.args["user"]
        summarize = bool(parameters.get("summarize", False))
        search = parameters.get("search", None)

        workflow = _get_workflow_with_uuid_or_name(workflow_id_or_name, user_uuid)
        disk_usage_info = workflow.get_workspace_disk_usage(
            summarize=summarize, search=search
        )
        response = {
            "workflow_id": workflow.id_,
            "workflow_name": workflow.name,
            "user": str(user_uuid),
            "disk_usage_info": disk_usage_info,
        }

        return jsonify(response), 200
    except REANAWorkflowControllerError as e:
        return jsonify({"message": str(e)}), 409
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except ValueError as e:
        return jsonify({"message": str(e)}), 403
    except Exception as e:
        return jsonify({"message": str(e)}), 500
