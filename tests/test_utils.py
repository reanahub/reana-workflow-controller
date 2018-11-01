# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-Workflow-Controller utilities tests."""

from reana_db.models import WorkflowStatus
from reana_workflow_controller.rest import _delete_workflow
from pytest_reana.fixtures import sample_yadage_workflow_in_db


def test_delete_workflow(app, sample_yadage_workflow_in_db):
    """Test delete_workflow()."""
    _delete_workflow(sample_yadage_workflow_in_db, {})
    assert sample_yadage_workflow_in_db.status == \
        WorkflowStatus.deleted
