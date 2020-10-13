# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller workflows REST API."""

import difflib
import logging
import os
import pprint
import subprocess
import traceback
from collections import OrderedDict
from datetime import datetime
from functools import wraps
from pathlib import Path

from kubernetes.client.rest import ApiException
from reana_commons.config import REANA_WORKFLOW_UMASK
from reana_commons.k8s.secrets import REANAUserSecretsStore
from reana_commons.utils import get_workflow_status_change_verb
from sqlalchemy.exc import SQLAlchemyError
from webargs import fields, validate
from webargs.flaskparser import parser
from werkzeug.exceptions import BadRequest

import fs
from flask import current_app as app
from flask import jsonify
from git import Repo
from reana_db.database import Session
from reana_db.models import Job, JobCache, Workflow, RunStatus
from reana_workflow_controller.config import REANA_GITLAB_HOST, WORKFLOW_TIME_FORMAT
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
        workflow.status = RunStatus.running
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
        item = {
            "workflow_uuid": str(job.workflow_uuid) or "",
            "job_name": job.job_name or "",
            "compute_backend": job.compute_backend or "",
            "backend_job_id": job.backend_job_id or "",
            "docker_img": job.docker_img or "",
            "cmd": job.prettified_cmd or "",
            "status": job.status.name or "",
            "logs": job.logs or "",
        }
        all_logs[str(job.id_)] = item

    return all_logs


def get_current_job_progress(workflow_id):
    """Return job."""
    current_job_commands = {}
    workflow_jobs = Session.query(Job).filter_by(workflow_uuid=workflow_id).all()
    for workflow_job in workflow_jobs:
        job = (
            Session.query(Job)
            .filter_by(id_=workflow_job.id_)
            .order_by(Job.created.desc())
            .first()
        )
        if job:
            current_job_commands[str(job.id_)] = {
                "prettified_cmd": job.prettified_cmd,
                "current_job_name": job.job_name,
            }
    return current_job_commands


def remove_workflow_jobs_from_cache(workflow):
    """Remove any cached jobs from given workflow.

    :param workflow: The workflow object that spawned the jobs.
    :return: None.
    """
    jobs = Session.query(Job).filter_by(workflow_uuid=workflow.id_).all()
    for job in jobs:
        job_path = remove_upper_level_references(
            os.path.join(workflow.workspace_path, "..", "archive", str(job.id_))
        )
        Session.query(JobCache).filter_by(job_id=job.id_).delete()
        remove_workflow_workspace(job_path)
    Session.commit()


def delete_workflow(workflow, all_runs=False, hard_delete=False, workspace=False):
    """Delete workflow."""
    if workflow.status in [
        RunStatus.created,
        RunStatus.finished,
        RunStatus.stopped,
        RunStatus.deleted,
        RunStatus.failed,
        RunStatus.queued,
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
                if hard_delete:
                    remove_workflow_workspace(workflow.workspace_path)
                    _delete_workflow_row_from_db(workflow)
                else:
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


def _delete_workflow_row_from_db(workflow):
    """Remove workflow row from database."""
    Session.query(Workflow).filter_by(id_=workflow.id_).delete()
    Session.commit()


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
    reana_fs = fs.open_fs(app.config["SHARED_VOLUME_PATH"])
    reana_fs.makedirs(path, recreate=True)
    if git_url and git_ref:
        secret_store = REANAUserSecretsStore(user_id)
        gitlab_access_token = secret_store.get_secret_value("gitlab_access_token")
        url = "https://oauth2:{0}@{1}/{2}.git".format(
            gitlab_access_token, REANA_GITLAB_HOST, git_url
        )
        repo = Repo.clone_from(
            url=url,
            to_path=os.path.abspath(reana_fs.root_path + "/" + path),
            branch=git_branch,
            depth=1,
        )
        repo.head.reset(commit=git_ref)


def remove_workflow_workspace(path):
    """Remove workflow workspace.

    :param path: Relative path to workspace directory.
    :return: None.
    """
    reana_fs = fs.open_fs(app.config["SHARED_VOLUME_PATH"])
    if reana_fs.exists(path):
        reana_fs.removetree(path)


def mv_files(source, target, workflow):
    """Move files within workspace."""
    absolute_workspace_path = os.path.join(
        app.config["SHARED_VOLUME_PATH"], workflow.workspace_path
    )
    absolute_source_path = os.path.join(
        app.config["SHARED_VOLUME_PATH"], absolute_workspace_path, source
    )
    absolute_target_path = os.path.join(
        app.config["SHARED_VOLUME_PATH"], absolute_workspace_path, target
    )

    if not os.path.exists(absolute_source_path):
        message = "Path {} does not exist".format(source)
        raise REANAWorkflowControllerError(message)
    if not absolute_source_path.startswith(absolute_workspace_path):
        message = "Source path is outside user workspace"
        raise REANAWorkflowControllerError(message)
    if not absolute_source_path.startswith(absolute_workspace_path):
        message = "Target path is outside workspace"
        raise REANAWorkflowControllerError(message)
    try:
        reana_fs = fs.open_fs(absolute_workspace_path)
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


def list_directory_files(directory):
    """Return a list of files inside a given directory."""
    fs_ = fs.open_fs(directory)
    file_list = []
    for file_name in fs_.walk.files():
        try:
            file_details = fs_.getinfo(file_name, namespaces=["details"])
            file_list.append(
                {
                    "name": file_name.lstrip("/"),
                    "last-modified": file_details.modified.strftime(
                        WORKFLOW_TIME_FORMAT
                    ),
                    "size": file_details.size,
                }
            )
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
    secure_path = remove_upper_level_references(path)
    posix_dir_prefix = Path(directory_path)
    paths = list(posix_dir_prefix.glob(secure_path))
    # sort paths by length to start with the leaves of the directory tree
    paths.sort(key=lambda path: len(str(path)), reverse=True)
    for posix_path in paths:
        try:
            file_name = str(posix_path.relative_to(posix_dir_prefix))
            object_size = posix_path.stat().st_size
            os.unlink(posix_path) if posix_path.is_file() else os.rmdir(posix_path)

            deleted["deleted"][file_name] = {"size": object_size}
        except Exception as e:
            deleted["failed"][file_name] = {"error": str(e)}

    return deleted


def remove_upper_level_references(path):
    """Remove upper than `./` references.

    Collapse separators/up-level references avoiding references to paths
    outside working directory.

    :param path: User provided path to a file or directory.
    :return: Returns the corresponding sanitized path.
    """
    return os.path.normpath("/" + path).lstrip("/")


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
    reana_fs = fs.open_fs(app.config["SHARED_VOLUME_PATH"])
    if reana_fs.exists(workspace_a) and reana_fs.exists(workspace_b):
        diff_command = [
            "diff",
            "--unified={}".format(context_lines),
            "-r",
            reana_fs.getospath(workspace_a),
            reana_fs.getospath(workspace_b),
        ]
        if brief:
            diff_command.append("-q")
        diff_result = subprocess.run(diff_command, stdout=subprocess.PIPE)
        diff_result_string = diff_result.stdout.decode("utf-8")
        diff_result_string = diff_result_string.replace(
            reana_fs.getospath(workspace_a).decode("utf-8"),
            get_workflow_name(workflow_a),
        )
        diff_result_string = diff_result_string.replace(
            reana_fs.getospath(workspace_b).decode("utf-8"),
            get_workflow_name(workflow_b),
        )

        return diff_result_string
    else:
        if not reana_fs.exists(workspace_a):
            raise ValueError(
                "Workspace of {} does not exist.".format(get_workflow_name(workflow_a))
            )
        if not reana_fs.exists(workspace_b):
            raise ValueError(
                "Workspace of {} does not exist.".format(get_workflow_name(workflow_b))
            )


def get_workflow_progress(workflow):
    """Return workflow progress information.

    :param workflow: The workflow to get progress information from.
    :type: reana_db.models.Workflow instance.

    :return: Dictionary with workflow progress information.
    """
    current_job_progress = get_current_job_progress(workflow.id_)
    cmd_and_step_name = {}
    try:
        _, cmd_and_step_name = current_job_progress.popitem()
    except Exception:
        pass
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
    initial_progress_status = {"total": 0, "job_ids": []}
    return {
        "total": (workflow.job_progress.get("total") or initial_progress_status),
        "running": (workflow.job_progress.get("running") or initial_progress_status),
        "finished": (workflow.job_progress.get("finished") or initial_progress_status),
        "failed": (workflow.job_progress.get("failed") or initial_progress_status),
        "current_command": cmd_and_step_name.get("prettified_cmd"),
        "current_step_name": cmd_and_step_name.get("current_job_name"),
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
    }


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
