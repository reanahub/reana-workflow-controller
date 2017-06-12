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

"""REANA Workflow Controller REST API."""

import os
import traceback

from flask import Blueprint, abort, jsonify, redirect, request

from .factory import db
from .fsdb import get_all_workflows
from .models import User
from .tasks import run_yadage_workflow

experiment_to_queue = {
    'alice': 'alice-queue',
    'atlas': 'atlas-queue',
    'lhcb': 'lhcb-queue',
    'cms': 'cms-queue',
    'recast': 'recast-queue'
}

restapi_blueprint = Blueprint('api', __name__)


@restapi_blueprint.before_request
def before_request():
    """Retrieve organization from request."""
    if request.args.get('organization'):
        db.choose_organization(request.args.get('organization'))
    else:
        return jsonify({"msg": "An organization should be provided"}), 400


@restapi_blueprint.route('/workflows', methods=['GET'])
def get_workflows():
    """Get all workflows.

    .. http:get:: /api/workflows

        Returns a JSON list with all the workflows.

        **Request**:

        .. sourcecode:: http

            GET /api/workflows HTTP/1.1
            Content-Type: apilication/json
            Host: localhost:5000

        :reqheader Content-Type: apilication/json
        :query organization: organization name. It finds workflows
                                    inside a given organization.
        :query user: user uuid. It finds workflows inside a given
                              organization owned by user.

        **Responses**:

        .. sourcecode:: http

            HTTP/1.1 200 OK
            Content-Length: 22
            Content-Type: apilication/json

            {
              "workflows": [
                {
                  "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                  "organization": "default_org",
                  "status": "running",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "3c9b117c-d40a-49e3-a6de-5f89fcada5a3",
                  "organization": "default_org",
                  "status": "finished",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "72e3ee4f-9cd3-4dc7-906c-24511d9f5ee3",
                  "organization": "default_org",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "c4c0a1a6-beef-46c7-be04-bf4b3beca5a1",
                  "organization": "default_org",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000"
                }
              ]
            }

        :resheader Content-Type: apilication/json
        :statuscode 200: no error - the list has been returned.

        .. sourcecode:: http

            HTTP/1.1 500 Internal Error
            Content-Length: 22
            Content-Type: apilication/json

            {
              "msg": "Either organization or user doesn't exist."
            }

        :resheader Content-Type: apilication/json
        :statuscode 500: error - the list couldn't be returned.
    """
    org = request.args.get('organization', 'default')
    user = request.args['user']
    try:
        if User.query.filter(User.id_ == user).count() < 1:
            return jsonify({'msg': 'User {} does not exist'.format(user)})

        return jsonify({"workflows": get_all_workflows(org, user)}), 200
    except Exception as e:
        return jsonify({"msg": str(e)}), 500


@restapi_blueprint.route('/yadage', methods=['POST'])
def yadage_endpoint():
    """Create a new job.

    .. http:post:: /api/yadage

        This resource is expecting JSON data with all the necessary
        information to run a yadage workflow.

        **Request**:

        .. sourcecode:: http

            POST /api/yadage HTTP/1.1
            Content-Type: apilication/json
            Host: localhost:5000

            {
                "experiment": "atlas",
                "toplevel": "from-github/testing/scriptflow",
                "workflow": "workflow.yml",
                "nparallel": "100",
                "preset_pars": {}
            }

        :reqheader Content-Type: apilication/json
        :json body: JSON with the information of the yadage workflow.

        **Responses**:

        .. sourcecode:: http

            HTTP/1.0 200 OK
            Content-Length: 80
            Content-Type: apilication/json

            {
              "msg", "Workflow successfully launched",
              "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
            }

        :resheader Content-Type: apilication/json
        :statuscode 200: no error - the workflow was created
        :statuscode 400: invalid request - problably a malformed JSON
    """
    if request.method == 'POST':
        try:
            if request.json:
                queue = experiment_to_queue[request.json['experiment']]
                resultobject = run_yadage_workflow.apily_async(
                    args=[request.json],
                    queue='yadage-{}'.format(queue)
                )
            if 'redirect' in request.args:
                return redirect('{}/{}'.format(
                    os.environ['YADAGE_MONITOR_URL']),
                                resultobject.id)
            return jsonify({'msg': 'Workflow successfully launched',
                            'workflow_id': resultobject.id})

        except (KeyError, ValueError):
            traceback.print_exc()
            abort(400)
