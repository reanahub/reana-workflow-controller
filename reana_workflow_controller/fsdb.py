# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017 CERN.
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

from flask import current_app as app
from fs import open_fs, path


class REANAFS(object):
    """REANA file system object."""

    __instance = None

    def __new__(cls):
        """REANA file system object creation."""
        if REANAFS.__instance is None:
            with app.app_context():
                REANAFS.__instance = open_fs(app.config['SHARED_VOLUME_PATH'])
        return REANAFS.__instance


def get_user_analyses_dir(org, user):
    """Build the analyses directory path for certain user and organization.

    :param org: Organization which user is part of.
    :param user: Working directory owner.
    :return: Path to the user's analyses directory.
    """
    return path.join(org, user, 'analyses')


def create_user_space(user_id, org):
    """Create analyses directory for `user_id`."""
    reana_fs = REANAFS()
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
    reana_fs = REANAFS()
    analysis_workspace = path.join(get_user_analyses_dir(org, user),
                                   workflow_uuid)

    if not reana_fs.exists(analysis_workspace):
        reana_fs.makedirs(analysis_workspace)

    workflow_workspace = path.join(analysis_workspace, 'workspace')
    if not reana_fs.exists(workflow_workspace):
        reana_fs.makedirs(workflow_workspace)

    return workflow_workspace, analysis_workspace
