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

"""Multiorganization management."""

from __future__ import absolute_import

from flask import current_app, g
from flask_sqlalchemy import SQLAlchemy


class MultiOrganizationSQLAlchemy(SQLAlchemy):
    """Multiorganization support for SQLAlchemy."""

    def _initialize_binds(self):
        """Initialize binds from configuration if necessary."""
        current_app.config['SQLALCHEMY_BINDS'] = {}
        for org in current_app.config.get('ORGANIZATIONS'):
            current_app.config['SQLALCHEMY_BINDS'][org] = current_app\
                       .config['SQLALCHEMY_DATABASE_URI'].replace(
                           'default/reana.db',
                           '{organization}/reana.db'.format(organization=org))

    def initialize_dbs(self):
        """Initialize all organizations dbs."""
        with current_app.app_context():
            # Default organization DB
            self.create_all()
            self._initialize_binds()
            for bind in current_app.config.get('SQLALCHEMY_BINDS').keys():
                self.choose_organization(bind)
                self.create_all()

    def choose_organization(self, bind_key):
        """Select a different bind."""
        # Set organization
        g.organization = bind_key

    def get_engine(self, app=None, bind=None):
        """Get engine depending on current bind."""
        if bind is None:
            if not hasattr(g, 'organization'):
                return super().get_engine(app=app)
            bind = g.organization
        return super().get_engine(app=app, bind=bind)
