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

"""REANA Workflow Controller command line interface."""

import click
from flask.cli import with_appcontext
from reana_commons.database import Session
from reana_commons.models import Organization, User, UserOrganization

from reana_workflow_controller import config
from reana_workflow_controller.utils import create_user_space


@click.group()
def users():
    """Record management commands."""


@users.command('create')
@click.argument('email')
@click.option('-o', '--organization', 'organization_name',
              type=click.Choice(config.ORGANIZATIONS),
              default='default')
@click.option('-i', '--id', 'id_',
              default='00000000-0000-0000-0000-000000000000')
@click.option('-k', '--key', 'key', default='secretkey')
@with_appcontext
def users_create_default(email, organization_name, id_, key):
    """Create new user."""
    user_characteristics = {"id_": id_,
                            "email": email,
                            "api_key": key
                            }
    user_organization_characteristics = {"user_id": id_,
                                         "name": organization_name}
    organization_characteristics = {"name": organization_name}
    try:
        user = User.query.filter_by(**user_characteristics).first()
        organization = Organization.query.filter_by(
            **organization_characteristics).first()
        user_organization = UserOrganization.query.filter_by(
            **user_organization_characteristics).first()
        if not organization:
            organization = Organization(**organization_characteristics)
            Session.add(organization)
            Session.commit()
        if not user:
            user = User(**user_characteristics)
            create_user_space(id_, organization_name)
            Session.add(user)
            Session.commit()
        if not user_organization:
            user_organization = UserOrganization(
                **user_organization_characteristics)
            Session.add(user_organization)
            Session.commit()
        click.echo(user.id_)
    except Exception as e:
        click.echo('Something went wrong: {0}'.format(e))
