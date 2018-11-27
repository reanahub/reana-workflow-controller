# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""Workflow persistence management."""

import os
from pathlib import Path

import fs
from flask import current_app as app
from reana_db.database import Session
from reana_db.models import Job, JobCache

from reana_workflow_controller.config import WORKFLOW_TIME_FORMAT


def create_workflow_workspace(path):
    """Create workflow workspace.

    :param path: Relative path to workspace directory.
    :return: Absolute workspace path.
    """
    reana_fs = fs.open_fs(app.config['SHARED_VOLUME_PATH'])
    if not reana_fs.exists(path):
        reana_fs.makedirs(path)


def list_directory_files(directory):
    """Return a list of files inside a given directory."""
    fs_ = fs.open_fs(directory)
    file_list = []
    for file_name in fs_.walk.files():
        file_details = fs_.getinfo(file_name, namespaces=['details'])
        file_list.append({'name': file_name.lstrip('/'),
                          'last-modified': file_details.modified.
                          strftime(WORKFLOW_TIME_FORMAT),
                          'size': file_details.size})
    return file_list


def remove_workflow_workspace(path):
    """Remove workflow workspace.

    :param path: Relative path to workspace directory.
    :return: None.
    """
    reana_fs = fs.open_fs(app.config['SHARED_VOLUME_PATH'])
    if reana_fs.exists(path):
        reana_fs.removetree(path)


def remove_workflow_jobs_from_cache(workflow):
    """Remove any cached jobs from given workflow.

    :param workflow: The workflow object that spawned the jobs.
    :return: None.
    """
    jobs = Session.query(Job).filter_by(workflow_uuid=workflow.id_).all()
    for job in jobs:
        job_path = os.path.join(workflow.get_workspace(),
                                '..', 'archive',
                                str(job.id_))
        Session.query(JobCache).filter_by(job_id=job.id_).delete()
        remove_workflow_workspace(job_path)
    Session.commit()


def remove_files_recursive_wildcard(directory_path, path):
    """Remove file(s) from workflow workspace.

    :param directory_path: FIXME.
    :param path: FIXME.
    :return: FIXME.
    """
    deleted = {"deleted": {}, "failed": {}}
    secure_path = remove_upper_level_references(path)
    posix_dir_prefix = Path(directory_path)
    paths = list(posix_dir_prefix.glob(secure_path))
    paths.sort(key=lambda path: len(str(path)), reverse=True)
    for posix_path in paths:
        try:
            file_name = str(posix_path.relative_to(posix_dir_prefix))
            object_size = posix_path.stat().st_size
            os.unlink(posix_path) if posix_path.is_file() \
                else os.rmdir(posix_path)

            deleted['deleted'][file_name] = \
                {"size": object_size}
        except Exception as e:
            deleted['failed'][file_name] = \
                {"error": str(e)}

    return deleted


def remove_upper_level_references(path):
    """Remove upper than `./` references.

    Collapse separators/up-level references avoiding references to paths
    outside working directory.

    :param path: User provided path to a file or directory.
    :return: Returns the corresponding sanitized path.
    """
    return os.path.normpath("/" + path).lstrip("/")
