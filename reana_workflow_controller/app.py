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

"""Rest API endpoint for workflow management."""

from __future__ import absolute_import

import os
import traceback

from flask import Flask, abort, jsonify, redirect, request

from .fsdb import get_all_workflows
from .multiorganization import MultiOrganizationSQLAlchemy
from .tasks import run_yadage_workflow

app = Flask(__name__)
app.config.from_object('reana_workflow_controller.config')
app.secret_key = "super secret key"

# Initialize DB
db = MultiOrganizationSQLAlchemy(app)

# Import models so that they are registered with SQLAlchemy
from .models import Tenant  # isort:skip # noqa

db.initialize_dbs()

experiment_to_queue = {
    'alice': 'alice-queue',
    'atlas': 'atlas-queue',
    'lhcb': 'lhcb-queue',
    'cms': 'cms-queue',
    'recast': 'recast-queue'
}


@app.before_request
def before_request():
    """Retrieve organization from request."""
    org = request.args.get('organization')
    if org:
        db.choose_organization(org)


@app.route('/workflows', methods=['GET'])
def get_workflows():
    """Get all workflows.

    .. http:get:: /workflows

        Returns a JSON list with all the workflows.

        **Request**:

        .. sourcecode:: http

            GET /workflows HTTP/1.1
            Content-Type: application/json
            Host: localhost:5000

        :reqheader Content-Type: application/json
        :query organization: organization name. It finds workflows
                                    inside a given organization.
        :query tenant: tenant uuid. It finds workflows inside a given
                              organization owned by tenant.

        **Responses**:

        .. sourcecode:: http

            HTTP/1.1 200 OK
            Content-Length: 22
            Content-Type: application/json

            {
              "workflows": [
                {
                  "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                  "organization": "default_org",
                  "status": "running",
                  "tenant": "default_tenant"
                },
                {
                  "id": "3c9b117c-d40a-49e3-a6de-5f89fcada5a3",
                  "organization": "default_org",
                  "status": "finished",
                  "tenant": "default_tenant"
                },
                {
                  "id": "72e3ee4f-9cd3-4dc7-906c-24511d9f5ee3",
                  "organization": "default_org",
                  "status": "waiting",
                  "tenant": "default_tenant"
                },
                {
                  "id": "c4c0a1a6-beef-46c7-be04-bf4b3beca5a1",
                  "organization": "default_org",
                  "status": "waiting",
                  "tenant": "default_tenant"
                }
              ]
            }

        :resheader Content-Type: application/json
        :statuscode 200: no error - the list has been returned.

        .. sourcecode:: http

            HTTP/1.1 500 Internal Error
            Content-Length: 22
            Content-Type: application/json

            {
              "msg": "Either organization or tenant doesn't exist."
            }

        :resheader Content-Type: application/json
        :statuscode 500: error - the list couldn't be returned.
    """
    org = request.args.get('organization', 'default')
    tenant = request.args['tenant']
    try:
        if Tenant.query.filter(Tenant.id_ == tenant).count() < 1:
            return jsonify({'msg': 'Tenant {} does not exist'.format(tenant)})

        return jsonify({"workflows": get_all_workflows(org, tenant)}), 200
    except Exception as e:
        return jsonify({"msg": str(e)}), 500


@app.route('/yadage', methods=['POST'])
def yadage_endpoint():
    """Create a new job.

    .. http:post:: /yadage

        This resource is expecting JSON data with all the necessary
        information to run a yadage workflow.

        **Request**:

        .. sourcecode:: http

            POST /yadage HTTP/1.1
            Content-Type: application/json
            Host: localhost:5000

            {
                "experiment": "atlas",
                "toplevel": "from-github/testing/scriptflow",
                "workflow": "workflow.yml",
                "nparallel": "100",
                "preset_pars": {}
            }

        :reqheader Content-Type: application/json
        :json body: JSON with the information of the yadage workflow.

        **Responses**:

        .. sourcecode:: http

            HTTP/1.0 200 OK
            Content-Length: 80
            Content-Type: application/json

            {
              "msg", "Workflow successfully launched",
              "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
            }

        :resheader Content-Type: application/json
        :statuscode 200: no error - the workflow was created
        :statuscode 400: invalid request - problably a malformed JSON
    """
    if request.method == 'POST':
        try:
            if request.json:
                queue = experiment_to_queue[request.json['experiment']]
                resultobject = run_yadage_workflow.apply_async(
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


if __name__ == '__main__':
    app.run(debug=True, port=5000,
            host='0.0.0.0')
