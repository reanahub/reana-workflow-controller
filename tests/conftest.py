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

import shutil
import tempfile
from os.path import dirname, join

import pytest

from reana_workflow_controller.app import app as reana_workflow_controller_app


@pytest.fixture
def tmp_fsdb_path(request):
    """Fixture data for XrootDPyFS."""
    path = tempfile.mkdtemp()
    shutil.copytree(join(dirname(__file__), "data"), join(path, "reana"))

    def cleanup():
        shutil.rmtree(path)

    request.addfinalizer(cleanup)
    return join(path, "reana")


@pytest.fixture()
def base_app(tmp_fsdb_path):
    """Flask application fixture."""
    app_ = reana_workflow_controller_app
    app_.config.from_object('reana_workflow_controller.config')
    app_.config['SHARED_VOLUME_PATH'] = tmp_fsdb_path
    app_.config.update(
        SERVER_NAME='localhost:5000',
        SECRET_KEY='SECRET_KEY',
        TESTING=True,
    )
    return app_


@pytest.yield_fixture()
def app(base_app):
    """Flask application fixture."""
    with base_app.app_context():
        yield base_app
