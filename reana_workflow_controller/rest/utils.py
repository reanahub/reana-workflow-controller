# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller workflows REST API."""

import difflib
import fs
import json
import logging
import mimetypes
import os
import pprint
import subprocess
import traceback
import time
import zipfile
import shutil
from collections import OrderedDict
from datetime import datetime
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional
from uuid import UUID

from flask import jsonify, request, send_file, send_from_directory
from git import Repo
from kubernetes.client.rest import ApiException
from reana_commons.config import REANA_WORKFLOW_UMASK, SHARED_VOLUME_PATH
from reana_commons.k8s.secrets import REANAUserSecretsStore
from reana_commons.utils import (
    get_workflow_status_change_verb,
    remove_upper_level_references,
    is_directory,
    get_files_recursive_wildcard,
)
from reana_db.database import Session
from reana_db.models import Job, JobCache, ResourceUnit, RunStatus, Workflow
from sqlalchemy.exc import SQLAlchemyError
from webargs import fields, validate
from webargs.flaskparser import parser
from werkzeug.exceptions import BadRequest, NotFound

from reana_workflow_controller.config import (
    REANA_GITLAB_HOST,
    WORKFLOW_TIME_FORMAT,
    PREVIEWABLE_MIME_TYPE_PREFIXES,
)
from reana_workflow_controller.errors import (
    REANAExternalCallError,
    REANAWorkflowControllerError,
    REANAWorkflowDeletionError,
    REANAWorkflowStatusError,
)
from reana_workflow_controller.workflow_run_manager import KubernetesWorkflowRunManager


def start_workflow(workflow, parameters):
    """Start a workflow."""

    def _start_workflow_db(workflow, parameters):
        workflow.status = RunStatus.pending
        if parameters:
            workflow.input_parameters = parameters.get("input_parameters")
            workflow.operational_options = parameters.get("operational_options")
        current_db_sessions.add(workflow)
        current_db_sessions.commit()

    current_db_sessions = Session.object_session(workflow)
    kwrm = KubernetesWorkflowRunManager(workflow)

    failure_message = (
        "Workflow {id_} could not be started because it {verb} " "already {status}."
    ).format(
        id_=workflow.id_,
        verb=get_workflow_status_change_verb(workflow.status.name),
        status=str(workflow.status.name),
    )
    if "restart" in parameters.keys():
        if parameters["restart"]:
            if workflow.status not in [
                RunStatus.failed,
                RunStatus.finished,
                RunStatus.queued,
                RunStatus.pending,
            ]:
                raise REANAWorkflowControllerError(failure_message)
    elif workflow.status not in [RunStatus.created, RunStatus.queued]:
        if workflow.status == RunStatus.deleted:
            raise REANAWorkflowStatusError(failure_message)
        raise REANAWorkflowControllerError(failure_message)

    try:
        kwrm.start_batch_workflow_run(
            overwrite_input_params=parameters.get("input_parameters"),
            overwrite_operational_options=parameters.get("operational_options"),
        )
        _start_workflow_db(workflow, parameters)
    except SQLAlchemyError as e:
        message = "Database connection failed, please retry."
        logging.error(
            f"Error while creating {workflow.id_}: {message}\n{e}", exc_info=True
        )
        # Rollback Kubernetes job creation
        kwrm.stop_batch_workflow_run()
        logging.error(
            f"Stopping Kubernetes jobs associated with workflow " f"{workflow.id_} ..."
        )
        raise REANAExternalCallError(message)
    except ApiException as e:
        message = "Kubernetes connection failed, please retry."
        logging.error(
            f"Error while creating {workflow.id_}: {message}\n{e}", exc_info=True
        )
        raise REANAExternalCallError(message)


def stop_workflow(workflow):
    """Stop a given workflow."""
    if workflow.status == RunStatus.running:
        kwrm = KubernetesWorkflowRunManager(workflow)
        kwrm.stop_batch_workflow_run()
        workflow.status = RunStatus.stopped
        Session.add(workflow)
        Session.commit()
    else:
        message = ("Workflow {id_} is not running.").format(id_=workflow.id_)
        raise REANAWorkflowControllerError(message)


def get_workflow_name(workflow):
    """Return a name of a Workflow.

    :param workflow: Workflow object which name should be returned.
    :type workflow: reana-commons.models.Workflow
    """
    return workflow.name + "." + str(workflow.run_number)


def build_workflow_logs(workflow, steps=None, paginate=None):
    """Return the logs for all jobs of a workflow."""
    query = Session.query(Job).filter_by(workflow_uuid=workflow.id_)
    if steps:
        query = query.filter(Job.job_name.in_(steps))
    query = query.order_by(Job.created)
    jobs = paginate(query).get("items") if paginate else query
    all_logs = OrderedDict()
    for job in jobs:
        started_at = (
            job.started_at.strftime(WORKFLOW_TIME_FORMAT) if job.started_at else None
        )
        finished_at = (
            job.finished_at.strftime(WORKFLOW_TIME_FORMAT) if job.finished_at else None
        )
        item = {
            "workflow_uuid": str(job.workflow_uuid) or "",
            "job_name": job.job_name or "",
            "compute_backend": job.compute_backend or "",
            "backend_job_id": job.backend_job_id or "",
            "docker_img": job.docker_img or "",
            "cmd": job.prettified_cmd or "",
            "status": job.status.name or "",
            "logs": job.logs or "",
            "started_at": started_at,
            "finished_at": finished_at,
        }
        all_logs[str(job.id_)] = item

    return all_logs


def remove_workflow_jobs_from_cache(workflow):
    """Remove any cached jobs from given workflow.

    :param workflow: The workflow object that spawned the jobs.
    :return: None.
    """
    jobs = Session.query(Job).filter_by(workflow_uuid=workflow.id_).all()
    for job in jobs:
        job_path = os.path.join(workflow.workspace_path, "..", "archive", str(job.id_))
        Session.query(JobCache).filter_by(job_id=job.id_).delete()
        remove_workflow_workspace(job_path)
    Session.commit()


def delete_workflow(workflow, all_runs=False, workspace=False):
    """Delete workflow."""
    if workflow.status in [
        RunStatus.created,
        RunStatus.finished,
        RunStatus.stopped,
        RunStatus.deleted,
        RunStatus.failed,
        RunStatus.queued,
        RunStatus.pending,
    ]:
        try:
            to_be_deleted = [workflow]
            if all_runs:
                to_be_deleted += (
                    Session.query(Workflow)
                    .filter(
                        Workflow.name == workflow.name,
                        Workflow.status != RunStatus.running,
                    )
                    .all()
                )
            for workflow in to_be_deleted:
                if workspace:
                    remove_workflow_workspace(workflow.workspace_path)
                _mark_workflow_as_deleted_in_db(workflow)
                remove_workflow_jobs_from_cache(workflow)

            return (
                jsonify(
                    {
                        "message": "Workflow successfully deleted",
                        "workflow_id": workflow.id_,
                        "workflow_name": get_workflow_name(workflow),
                        "status": workflow.status.name,
                        "user": str(workflow.owner_id),
                    }
                ),
                200,
            )
        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"message": str(e)}), 500
    elif workflow.status == RunStatus.running:
        raise REANAWorkflowDeletionError(
            "Workflow {0}.{1} cannot be deleted as it"
            " is currently running.".format(workflow.name, workflow.run_number)
        )


def _mark_workflow_as_deleted_in_db(workflow):
    """Mark workflow as deleted."""
    workflow.status = RunStatus.deleted
    current_db_sessions = Session.object_session(workflow)
    current_db_sessions.add(workflow)
    current_db_sessions.commit()


def get_specification_diff(workflow_a, workflow_b, output_format="unified"):
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

    def _aggregated_inputs(workflow):
        inputs = workflow.reana_specification.get("inputs", {})
        input_parameters = inputs.get("parameters", {})
        if workflow.input_parameters:
            input_parameters = dict(input_parameters, **workflow.input_parameters)
            inputs["parameters"] = input_parameters
        return inputs

    if output_format not in ["unified", "context", "html"]:
        raise ValueError(
            "Unknown output format." "Please select one of unified, context or html."
        )

    if output_format == "unified":
        diff_method = getattr(difflib, "unified_diff")
    elif output_format == "context":
        diff_method = getattr(difflib, "context_diff")
    elif output_format == "html":
        diff_method = getattr(difflib, "HtmlDiff")

    specification_diff = dict.fromkeys(workflow_a.reana_specification.keys())
    for section in specification_diff:
        if section == "inputs":
            section_value_a = _aggregated_inputs(workflow_a)
            section_value_b = _aggregated_inputs(workflow_b)
        else:
            section_value_a = workflow_a.reana_specification.get(section, "")
            section_value_b = workflow_b.reana_specification.get(section, "")
        section_a = pprint.pformat(section_value_a).splitlines()
        section_b = pprint.pformat(section_value_b).splitlines()
        # skip first 2 lines of diff relevant if input comes from files
        specification_diff[section] = list(diff_method(section_a, section_b))[2:]
    return specification_diff


# Workspace utils


def create_workflow_workspace(
    path, user_id=None, git_url=None, git_branch=None, git_ref=None
):
    """Create workflow workspace.

    :param path: Relative path to workspace directory.
    :return: Absolute workspace path.
    """
    os.umask(REANA_WORKFLOW_UMASK)
    os.makedirs(path, exist_ok=True)
    if git_url and git_ref:
        secret_store = REANAUserSecretsStore(user_id)
        gitlab_access_token = secret_store.get_secret_value("gitlab_access_token")
        url = "https://oauth2:{0}@{1}/{2}.git".format(
            gitlab_access_token, REANA_GITLAB_HOST, git_url
        )
        repo = Repo.clone_from(
            url=url, to_path=os.path.abspath(path), branch=git_branch, depth=1,
        )
        repo.head.reset(commit=git_ref)


def remove_workflow_workspace(path):
    """Remove workflow workspace.

    :param path: Relative path to workspace directory.
    :return: None.
    """
    if os.path.isdir(path):
        shutil.rmtree(path)


def mv_files(source, target, workflow):
    """Move files within workspace."""
    absolute_source_path = os.path.join(workflow.workspace_path, source)

    if not os.path.exists(absolute_source_path):
        message = "Path {} does not exist".format(source)
        raise REANAWorkflowControllerError(message)
    if not absolute_source_path.startswith(workflow.workspace_path):
        message = "Source path is outside user workspace"
        raise REANAWorkflowControllerError(message)
    if not absolute_source_path.startswith(workflow.workspace_path):
        message = "Target path is outside workspace"
        raise REANAWorkflowControllerError(message)
    try:
        reana_fs = fs.open_fs(workflow.workspace_path)
        source_info = reana_fs.getinfo(source)
        if source_info.is_dir:
            reana_fs.movedir(src_path=source, dst_path=target, create=True)
        else:
            reana_fs.move(src_path=source, dst_path=target)
        reana_fs.close()
    except Exception as e:
        reana_fs.close()
        message = "Something went wrong:\n {}".format(e)
        raise REANAWorkflowControllerError(message)


def list_directory_files(directory, search=None):
    """Return a list of files inside a given directory."""
    fs_ = fs.open_fs(directory)
    file_list = []
    for file_name in fs_.walk.files():
        try:
            file_details = fs_.getinfo(file_name, namespaces=["details"])
            file_info = {
                "name": file_name.lstrip("/"),
                "last-modified": file_details.modified.strftime(WORKFLOW_TIME_FORMAT),
                "size": dict(
                    raw=file_details.size,
                    human_readable=ResourceUnit.human_readable_unit(
                        ResourceUnit.bytes_, file_details.size
                    ),
                ),
            }
            if search:
                filter_file = list_files_filter(file_info, search)
                if filter_file:
                    file_list.append(file_info)
            else:
                file_list.append(file_info)
        except fs.errors.ResourceNotFound as e:
            if os.path.islink(fs_.root_path + file_name):
                target = os.path.realpath(fs_.root_path + file_name)
                msg = "Symbolic link {} targeting {} could not be resolved: \
                {}".format(
                    file_name, target, e
                )
                logging.error(msg, exc_info=True)
            continue
    return file_list


def remove_files_recursive_wildcard(directory_path, path):
    """Remove file(s) fitting the wildcard from the workspace.

    :param directory_path: Directory to delete files from.
    :param path: Wildcard pattern to use for the removal.
    :return: Dictionary with the results:
       - dictionary with names of succesfully deleted files and their sizes
       - dictionary with names of failed deletions and corresponding
       error messages.
    """
    deleted = {"deleted": {}, "failed": {}}
    paths, posix_dir_prefix = get_files_recursive_wildcard(directory_path, path)
    for posix_path in paths:
        try:
            file_name = str(posix_path.relative_to(posix_dir_prefix))
            object_size = posix_path.stat().st_size
            os.unlink(posix_path) if posix_path.is_file() else os.rmdir(posix_path)

            deleted["deleted"][file_name] = {"size": object_size}
        except Exception as e:
            deleted["failed"][file_name] = {"error": str(e)}

    return deleted


def list_files_recursive_wildcard(directory_path, path, search=None):
    """List file(s) fitting the wildcard from the workspace.

    :param directory_path: Directory to list files from.
    :param path: Wildcard pattern to use for the listing.
    :return: Dictionary with the results:
       - dictionary with names of succesfully listed files and their sizes
       - dictionary with names of failed listing and corresponding
       error messages.
    """
    paths, posix_dir_prefix = get_files_recursive_wildcard(directory_path, path)
    list_files_recursive = []
    for path in paths:
        raw_size = path.stat().st_size
        file_info = {
            "name": str(path.relative_to(posix_dir_prefix)),
            "size": dict(
                raw=raw_size,
                human_readable=ResourceUnit.human_readable_unit(
                    ResourceUnit.bytes_, raw_size
                ),
            ),
            "last-modified": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                WORKFLOW_TIME_FORMAT
            ),
        }
        if search:
            filter_file = list_files_filter(file_info, search)
            if filter_file:
                list_files_recursive.append(file_info)
        else:
            list_files_recursive.append(file_info)
    return list_files_recursive


def list_files_filter(file_info, search_filters):
    """Filter the file(s) matching the searching parameters.

    :param file_info: names of files and their sizes
    :param search_filters: search parameters based on `name`
                           `size` and `last-modified`.

    :return: Boolean after matching with searching filters.
    """
    filter_file = False
    _file = {
        "name": file_info["name"],
        "size": str(file_info["size"]["raw"]),
        "last-modified": file_info["last-modified"],
    }
    # Filter file only if all filters match exclusively.
    if all(_filter in _file[k] for k, v in search_filters.items() for _filter in v):
        filter_file = True
    return filter_file


def download_files_recursive_wildcard(workflow_name, workspace_path, path):
    """Download file(s) matching the given path pattern from the workspace.

    This function finds out if the provided pattern corresponds to:
    - a single file; then serves it directly
    - a directory; then packages it into a zip file
    - multiple files; then packages them into a zip file

    :param workflow_name: Full workflow name including run number.
    :param workspace_path: Base workspace directory where files are located.
    :param path: (Wildcard) pattern to use for the download.
    :return: Flask function call to send file to the client.
    """

    def _send_zipped_dir_or_files(workflow_name, dir_path=None, file_paths=None):
        """Wrap directory into a zip file in memory and send it to the client."""
        timestr = time.strftime("%Y-%m-%d-%H%M%S")
        filename = "download_{}_{}_{}.zip".format(
            workflow_name,
            os.path.basename(remove_upper_level_references(path)),
            timestr,
        )
        memory_file = BytesIO()
        with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            if dir_path:
                if len(list(dir_path.iterdir())):
                    for root, dirs, files in os.walk(dir_path):
                        for file in files:
                            zipf.write(
                                os.path.join(root, file),
                                arcname=os.path.join(
                                    path, str(Path(root).relative_to(dir_path)), file
                                ),
                            )
                else:
                    raise NotFound("The provided directory is empty.")
            elif file_paths:
                for file_path in file_paths:
                    zipf.write(
                        file_path,
                        arcname=str(file_path.relative_to(Path(workspace_path))),
                    )
            else:
                raise NotFound("The provided pattern does not match any file.")
        memory_file.seek(0)
        return send_file(
            memory_file,
            attachment_filename=filename,
            as_attachment=True,
            mimetype="application/zip",
        )

    def _send_single_file(absolute_file_path: str, workspace_path: str):
        """Send single file from directory to the client."""
        default_response_mime_type = "multipart/form-data"
        preview = json.loads(request.args.get("preview", "false").lower())
        response_mime_type = default_response_mime_type
        file_mime_type = get_previewable_mime_type(path)
        if preview and file_mime_type:
            response_mime_type = file_mime_type
        relative_file_path = str(absolute_file_path.relative_to(workspace_path))
        return (
            send_from_directory(
                workspace_path,
                relative_file_path,
                mimetype=response_mime_type,
                as_attachment=response_mime_type == default_response_mime_type,
                attachment_filename=relative_file_path,
            ),
            200,
        )

    full_path_dir = is_directory(workspace_path, path)
    if full_path_dir:
        return _send_zipped_dir_or_files(workflow_name, dir_path=full_path_dir)

    else:
        paths, _ = get_files_recursive_wildcard(workspace_path, path)
        # filter out non-files
        paths = [path for path in paths if path.is_file()]
        # if it's a single file, serve it directly
        if len(paths) == 1:
            absolute_file_path = paths[0]
            return _send_single_file(absolute_file_path, workspace_path)
        # if multiple files, package them into a zip file and serve it
        else:
            return _send_zipped_dir_or_files(workflow_name, file_paths=paths)


def get_previewable_mime_type(path: str) -> Optional[str]:
    """Get the response mime-type of the given file path.

    Takes into account previewable configuration.
    :return: The file mime type if previewable, else ``None``.
    """
    mime_type = mimetypes.guess_type(path)[0]
    if mime_type and any(
        mime_type.startswith(mt) for mt in PREVIEWABLE_MIME_TYPE_PREFIXES
    ):
        return mime_type
    return None


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
    workspace_a = workflow_a.workspace_path
    workspace_b = workflow_b.workspace_path
    if os.path.exists(workspace_a) and os.path.exists(workspace_b):
        diff_command = [
            "diff",
            "--unified={}".format(context_lines),
            "-r",
            workspace_a,
            workspace_b,
        ]
        if brief:
            diff_command.append("-q")
        diff_result = subprocess.run(diff_command, stdout=subprocess.PIPE)
        diff_result_string = diff_result.stdout.decode("utf-8")
        diff_result_string = diff_result_string.replace(
            workspace_a, get_workflow_name(workflow_a),
        )
        diff_result_string = diff_result_string.replace(
            workspace_b, get_workflow_name(workflow_b),
        )

        return diff_result_string
    else:
        if not os.path.exists(workspace_a):
            raise ValueError(
                "Workspace of {} does not exist.".format(get_workflow_name(workflow_a))
            )
        if not os.path.exists(workspace_b):
            raise ValueError(
                "Workspace of {} does not exist.".format(get_workflow_name(workflow_b))
            )


def get_most_recent_job_info(workflow_id: UUID) -> Dict[str, str]:
    """Return most recent Job cmd and name from a certain workflow."""
    current_job_commands = {}
    most_recent_job = (
        Session.query(Job)
        .filter_by(workflow_uuid=workflow_id)
        .order_by(Job.created.desc())
        .first()
    )
    if most_recent_job:
        current_job_commands = {
            "prettified_cmd": most_recent_job.prettified_cmd,
            "current_job_name": most_recent_job.job_name,
        }
    return current_job_commands


def get_workflow_progress(workflow: Workflow, include_progress: bool = False) -> Dict:
    """Return workflow progress information.

    :param workflow: The workflow to get progress information from.
    :type: reana_db.models.Workflow instance.
    :param include_progress: Whether or not to include the job progress information.
    :type: bool.

    :return: Dictionary with workflow progress information.
    """
    run_started_at = (
        workflow.run_started_at.strftime(WORKFLOW_TIME_FORMAT)
        if workflow.run_started_at
        else None
    )
    run_finished_at = (
        workflow.run_finished_at.strftime(WORKFLOW_TIME_FORMAT)
        if workflow.run_finished_at
        else None
    )
    progress = {
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
    }

    if include_progress:
        initial_progress_status = {"total": 0, "job_ids": []}
        most_recent_job_info = get_most_recent_job_info(workflow.id_)
        return {
            "total": (workflow.job_progress.get("total") or initial_progress_status),
            "running": (
                workflow.job_progress.get("running") or initial_progress_status
            ),
            "finished": (
                workflow.job_progress.get("finished") or initial_progress_status
            ),
            "failed": (workflow.job_progress.get("failed") or initial_progress_status),
            "current_command": most_recent_job_info.get("prettified_cmd"),
            "current_step_name": most_recent_job_info.get("current_job_name"),
            **progress,
        }

    return progress


def use_paginate_args():
    """Get and validate pagination arguments.

    :return: `paginate` function to use in decorated rest endpoint.
    """

    def decorator(f):
        @wraps(f)
        def inner(*args, **kwargs):
            try:
                req = parser.parse(
                    {
                        "page": fields.Int(validate=validate.Range(min=1)),
                        "size": fields.Int(validate=validate.Range(min=1)),
                    },
                    location="querystring",
                    error_status_code=400,
                )
            # For validation errors, webargs raises an enhanced BadRequest
            except BadRequest as err:
                return jsonify({"message": err.data.get("messages")}), err.code

            # Default if page is not specified
            if not req.get("page"):
                req["page"] = 1

            if req.get("size"):
                req.update(
                    dict(
                        from_idx=(req["page"] - 1) * req["size"],
                        to_idx=req["page"] * req["size"],
                        links=dict(
                            prev={"page": req["page"] - 1},
                            self={"page": req["page"]},
                            next={"page": req["page"] + 1},
                        ),
                    )
                )

            def paginate(query_or_list):
                """Paginate based on received page and size args.

                :param query_or_list: Query or list to paginate.
                :type: sqlalchemy.orm.query.Query | list.

                :return: Dictionary with paginated items and some useful information.
                """
                items = query_or_list
                has_prev, has_next = False, False
                total = (
                    len(query_or_list)
                    if isinstance(query_or_list, list)
                    else query_or_list.count()
                )
                if req.get("size"):
                    if isinstance(query_or_list, list):
                        items = query_or_list[req["from_idx"] : req["to_idx"]]
                        total = len(query_or_list)
                        has_next = req["to_idx"] < total
                    else:
                        items = query_or_list.slice(req["from_idx"], req["to_idx"])
                        total = query_or_list.count()
                        has_next = req["to_idx"] < total
                    has_prev = req["from_idx"] > 0
                req.update(
                    dict(items=items, has_prev=has_prev, has_next=has_next, total=total)
                )
                return req

            return f(paginate=paginate, *args, **kwargs)

        return inner

    return decorator
