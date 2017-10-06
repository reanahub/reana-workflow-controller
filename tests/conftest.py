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

import pytest

from reana_workflow_controller.factory import create_app, db
from reana_workflow_controller.models import User


@pytest.fixture
def tmp_shared_volume_path(tmpdir_factory):
    """Fixture temporary file system database."""
    temp_path = str(tmpdir_factory.mktemp('data').join('reana'))
    shutil.copytree(os.path.join(os.path.dirname(__file__), "data"),
                    temp_path)

    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture()
def base_app(tmp_shared_volume_path):
    """Flask application fixture."""
    config_mapping = {
        'SERVER_NAME': 'localhost:5000',
        'SECRET_KEY': 'SECRET_KEY',
        'TESTING': True,
        'SHARED_VOLUME_PATH': tmp_shared_volume_path,
        'SQLALCHEMY_DATABASE_URI_TEMPLATE':
        'sqlite:///{0}/default/reana.db'.format(tmp_shared_volume_path),
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'ORGANIZATIONS': ['default'],
    }
    app_ = create_app(config_mapping)
    return app_


@pytest.fixture()
def app(base_app):
    """Flask application fixture."""
    with base_app.app_context():
        yield base_app


@pytest.fixture()
def default_user(app):
    """Create users."""
    db.choose_organization('default')
    user = User(id_='00000000-0000-0000-0000-000000000000',
                email='info@reana.io', api_key='secretkey')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def db_session():
    """DB fixture"""
    yield db.session
    db.session.close()
