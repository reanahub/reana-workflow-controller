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


def get_user_analyses_dir(org, user):
    """Build the analyses directory path for certain user and organization.

    :param org: Organization which user is part of.
    :param user: Working directory owner.
    :return: Path to the user's analyses directory.
    """
    return fs.path.join(org, user, 'analyses')


def create_user_space(user_id, org):
    """Create analyses directory for `user_id`."""
    reana_fs = fs.open_fs(app.config['SHARED_VOLUME_PATH'])
    user_analyses_dir = get_user_analyses_dir(org, user_id)
    if not reana_fs.exists(user_analyses_dir):
        reana_fs.makedirs(user_analyses_dir)


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
            fs.path.join(workflow_workspace,
                         app.config['INPUTS_RELATIVE_PATH']))
        reana_fs.makedirs(
            fs.path.join(workflow_workspace,
                         app.config['OUTPUTS_RELATIVE_PATH']))

    return workflow_workspace, analysis_workspace


def list_directory_files(directory):
    """Return a list of files contained in a directory."""
    fs_ = fs.open_fs(directory)
    file_list = []
    for file_name in fs_.walk.files():
        file_details = fs_.getinfo(file_name, namespaces=['details'])
        file_list.append({'name': file_name.lstrip('/'),
                          'last-modified': file_details.modified.isoformat(),
                          'size': file_details.size})
    return file_list
