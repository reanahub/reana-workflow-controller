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

"""Pytest configuration for REANA-Workflow-Controller."""

from __future__ import absolute_import, print_function

import os
import shutil
import tempfile

import pytest

from reana_workflow_controller.factory import create_app, db
from reana_workflow_controller.models import User


@pytest.fixture
def tmp_fsdb_path(request):
    """Fixture temporary file system database."""
    path = tempfile.mkdtemp()
    shutil.copytree(os.path.join(os.path.dirname(__file__), "data"),
                    os.path.join(path, "reana"))

    def cleanup():
        shutil.rmtree(path)

    request.addfinalizer(cleanup)
    return os.path.join(path, "reana")


@pytest.yield_fixture()
def base_app(tmp_fsdb_path):
    """Flask application fixture."""
    os.environ['SHARED_VOLUME_PATH'] = tmp_fsdb_path
    os.environ['ORGANIZATIONS'] = 'default'
    app_ = create_app()
    app_.config.update(
        SERVER_NAME='localhost:5000',
        SECRET_KEY='SECRET_KEY',
        TESTING=True,
    )
    yield app_
    del os.environ['ORGANIZATIONS']
    del os.environ['SHARED_VOLUME_PATH']


@pytest.yield_fixture()
def app(base_app):
    """Flask application fixture."""
    with base_app.app_context():
        yield base_app


@pytest.yield_fixture()
def default_user(app):
    """Create users."""
    db.choose_organization('default')
    user = User(id_='00000000-0000-0000-0000-000000000000',
                email='info@reana.io', api_key='secretkey')
    db.session.add(user)
    db.session.commit()
    return user
