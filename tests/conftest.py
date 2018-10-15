# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Pytest configuration for REANA-Workflow-Controller."""

from __future__ import absolute_import, print_function

import os
import shutil

import pytest
from reana_db.models import Base, User
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy_utils import create_database, database_exists, drop_database

from reana_workflow_controller.factory import create_app


@pytest.fixture(scope='module')
def base_app(tmp_shared_volume_path):
    """Flask application fixture."""
    config_mapping = {
        'SERVER_NAME': 'localhost:5000',
        'SECRET_KEY': 'SECRET_KEY',
        'TESTING': True,
        'SHARED_VOLUME_PATH': tmp_shared_volume_path,
        'SQLALCHEMY_DATABASE_URI':
        'sqlite:///',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'ORGANIZATIONS': ['default'],
    }
    app_ = create_app(config_mapping)
    return app_
