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

"""Rest API endpoint for workflow management."""

from __future__ import absolute_import

from flask import Flask
from reana_db.database import Session

from reana_db.models import Base  # isort:skip  # noqa


def create_app(config_mapping=None):
    """REANA Workflow Controller application factory."""
    app = Flask(__name__)
    app.config.from_object('reana_workflow_controller.config')
    if config_mapping:
        app.config.from_mapping(config_mapping)

    app.secret_key = "super secret key"
    # Register API routes
    from .rest import restapi_blueprint  # noqa
    app.register_blueprint(restapi_blueprint, url_prefix='/api')
    app.session = Session
    return app
