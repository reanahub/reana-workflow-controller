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

from enum import Enum

from flask import current_app as app
from fs import open_fs, path
from fs.errors import CreateFailed, ResourceNotFound


class REANAFS(object):
    """REANA file system object."""

    __instance = None

    def __new__(cls):
        """REANA file system object creation."""
        if REANAFS.__instance is None:
            with app.app_context():
                REANAFS.__instance = open_fs(app.config['SHARED_VOLUME_PATH'])
        return REANAFS.__instance


class WorkflowStatus(Enum):
    """WorkflowStatus enumeration."""

    waiting = 0
    running = 1
    finished = 2
    stopped = 3
    paused = 4


def get_all_workflows(org, user, status=None):
    """Get workflows from file system.

    :param org: Organization which user is part of.
    :param user: Worklow owner.
    :param status: Filter workflows by status. If not provided no filter
        is applyied.
    :return: List of dictionaries containing the workflow data.
    :raises fs.errors.CreateFailed: Probably the configured path doesn't exist.
    :raises fs.errors.ResourceNotFound: Probably either org or user doesn't
        exist.
    """
    try:
        reana_fs = REANAFS()
        workflows = []
        user_analyses_dir = path.join(org, user, 'analyses')

        for name in reana_fs.walk.files(
                user_analyses_dir,
                filter=['.status.{0}'.format(status.name)] if status else [],
                exclude_dirs=[
                    'workspace',
                ]):
            # /:org/:user/analyses/:workflow_uuid/.status.WorkflowStatus
            # /atlas/default_user/analyses/256b25f4-4cfb-4684-b7a8-73872ef455a1/.status.waiting
            path_data = name.split('/')
            uuid = path_data[4]
            status = path_data[-1].split('.')[-1]
            workflows.append({'id': uuid, 'status': status,
                              'organization': org, 'user': user})

        return workflows

    except CreateFailed:
        raise Exception("Couldn't load database.")
    except ResourceNotFound:
        raise Exception("Either org or user doesn't exist.")


def create_user_space(user_id, org):
    """Create analyses directory for `user_id`."""
    reana_fs = REANAFS()
    user_analyses_dir = path.join(org, user_id, 'analyses')
    if not reana_fs.exists(user_analyses_dir):
        reana_fs.makedirs(user_analyses_dir)
