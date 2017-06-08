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
"""REANA-Workflow-Controller fsdb module tests."""

from __future__ import absolute_import, print_function

import json

from flask import url_for


def test_get_workflows(app, default_tenant):
    """Test listing all workflows."""
    with app.test_client() as client:
        res = client.get(url_for('api.get_workflows'),
                         query_string={"tenant":
                                       default_tenant.id_})
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))
        expected_data = {
            "workflows": [
                {
                    "id": "3fd74dc6-6307-4d22-9853-cc1895610080",
                    "organization": "default",
                    "status": "running",
                    "tenant": "00000000-0000-0000-0000-000000000000"
                }
            ]
        }

        assert response_data == expected_data
