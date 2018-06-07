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
"""Workflow persistence management."""

import fs
from flask import current_app as app
from reana_commons.utils import get_user_analyses_dir


def create_workflow_workspace(org, user, workflow_uuid):
    """Create analysis and workflow workspaces.

    A directory structure will be created where `/:analysis_uuid` represents
    the analysis workspace and `/:analysis_uuid/workspace` the workflow
    workspace.

    :param org: Organization which user is part of.
    :param user: Workspaces owner.
    :param workflow_uuid: Analysis UUID.
    :return: Workflow and analysis workspace path.
    """
    reana_fs = fs.open_fs(app.config['SHARED_VOLUME_PATH'])
    analysis_workspace = fs.path.join(get_user_analyses_dir(org, user),
                                      workflow_uuid)

    if not reana_fs.exists(analysis_workspace):
        reana_fs.makedirs(analysis_workspace)

    workflow_workspace = fs.path.join(analysis_workspace, 'workspace')
    if not reana_fs.exists(workflow_workspace):
        reana_fs.makedirs(workflow_workspace)
        reana_fs.makedirs(
            fs.path.join(analysis_workspace,
                         app.config['INPUTS_RELATIVE_PATH']))
        reana_fs.makedirs(
            fs.path.join(analysis_workspace,
                         app.config['OUTPUTS_RELATIVE_PATH']))
        reana_fs.makedirs(
            fs.path.join(analysis_workspace,
                         app.config['CODE_RELATIVE_PATH']))

    return workflow_workspace, analysis_workspace


def get_analysis_dir(workflow):
    """Given a workflow, returns its analysis directory."""
    # remove workflow workspace (/workspace) directory from path
    analysis_workspace = fs.path.dirname(workflow.workspace_path)
    return fs.path.join(app.config['SHARED_VOLUME_PATH'],
                        analysis_workspace)


def get_analysis_files_dir(workflow, file_type, action='list'):
    """Given a workflow and a file type, returns path to the file type dir."""
    analysis_workspace = get_analysis_dir(workflow)
    if action == 'list':
        return fs.path.join(analysis_workspace,
                            app.config['ALLOWED_LIST_DIRECTORIES'][file_type])
    elif action == 'seed':
        return fs.path.join(analysis_workspace,
                            app.config['ALLOWED_SEED_DIRECTORIES'][file_type])


def list_directory_files(directory):
    """Return a list of files of a given type for an analysis."""
    fs_ = fs.open_fs(directory)
    file_list = []
    for file_name in fs_.walk.files():
        file_details = fs_.getinfo(file_name, namespaces=['details'])
        file_list.append({'name': file_name.lstrip('/'),
                          'last-modified': file_details.modified.isoformat(),
                          'size': file_details.size})
    return file_list
