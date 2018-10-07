# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""Workflow persistence management."""

import fs
import fs.path as fs_path
from flask import current_app as app

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
