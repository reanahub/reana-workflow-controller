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

"""Models for REANA Workflow Controller."""

from __future__ import absolute_import

import enum

from sqlalchemy.schema import UniqueConstraint
from sqlalchemy_utils.types import JSONType, UUIDType

from .factory import db


class User(db.Model):
    """User model."""

    id_ = db.Column(UUIDType, primary_key=True)
    api_key = db.Column(db.String(120))
    create_date = db.Column(db.DateTime, default=db.func.now())
    email = db.Column(db.String(255), unique=True)
    last_active_date = db.Column(db.DateTime)
    workflows = db.relationship('Workflow', backref='user', lazy=True)

    def __init__(self, id_, email, api_key):
        """Initialize user model."""
        self.id_ = id_
        self.email = email
        self.api_key = api_key

    def __repr__(self):
        """User string represetantion."""
        return '<User %r>' % self.id_


class WorkflowStatus(enum.Enum):
    """Possible workflow status list enum."""

    created = 0
    running = 1
    finished = 2
    failed = 3


class Workflow(db.Model):
    """Workflow model."""

    id_ = db.Column(UUIDType, unique=True, primary_key=True)
    name = db.Column(db.String(255))
    run_number = db.Column(db.Integer)
    create_date = db.Column(db.DateTime, default=db.func.now())
    workspace_path = db.Column(db.String(255))
    status = db.Column(db.Enum(WorkflowStatus), default=WorkflowStatus.created)
    owner_id = db.Column(UUIDType, db.ForeignKey('user.id_'), nullable=False)
    specification = db.Column(JSONType)
    parameters = db.Column(JSONType)
    type_ = db.Column(db.String(30))
    logs = db.Column(db.String, default="")
    __table_args__ = UniqueConstraint('name', 'owner_id', 'run_number',
                                      name='_user_workflow_run_uc'),

    def __init__(self, id_, name, workspace_path, owner_id,
                 specification, parameters, type_,
                 status=WorkflowStatus.created):
        """Initialize workflow model."""
        self.id_ = id_
        self.name = name
        self.workspace_path = workspace_path
        self.owner_id = owner_id
        self.specification = specification
        self.parameters = parameters
        self.type_ = type_
        self.status = status
        last_workflow = Workflow.query.filter_by(
            name=name,
            owner_id=owner_id).\
            order_by(Workflow.run_number.desc()).first()
        if not last_workflow:
            self.run_number = 1
        else:
            self.run_number = last_workflow.run_number + 1

    def __repr__(self):
        """Workflow string represetantion."""
        return '<Workflow %r>' % self.id_
