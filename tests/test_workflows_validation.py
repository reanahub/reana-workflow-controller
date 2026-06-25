# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for the workflow specification validation REST endpoint."""

from flask import Flask
from mock import patch

from reana_workflow_controller.rest import workflows_validation


def _test_app():
    """Build the smallest Flask application that exercises the blueprint."""
    app = Flask(__name__)
    app.register_blueprint(workflows_validation.blueprint, url_prefix="/api")
    return app


def test_validate_workflow_spec_returns_sandbox_report():
    """A completed loader report is passed through to the server."""
    report = {"reana_specification": {"workflow": {"type": "serial"}}}
    with patch.object(
        workflows_validation,
        "validate_spec_in_sandbox",
        return_value=(0, report),
    ):
        response = (
            _test_app()
            .test_client()
            .post(
                "/api/workflows/validate",
                json={"bundle_path": "validation-tmp/abcd"},
            )
        )

    assert response.status_code == 200
    assert response.get_json() == {"exit_code": 0, "report": report}


def test_validate_workflow_spec_hides_unexpected_exception(caplog):
    """Unexpected exception details stay in logs and never reach the caller."""
    secret_detail = "Kubernetes request failed for /sensitive/workspace"
    with patch.object(
        workflows_validation,
        "validate_spec_in_sandbox",
        side_effect=RuntimeError(secret_detail),
    ):
        response = (
            _test_app()
            .test_client()
            .post(
                "/api/workflows/validate",
                json={"bundle_path": "validation-tmp/abcd"},
            )
        )

    assert response.status_code == 500
    body = response.get_json()
    assert body["message"] == workflows_validation.VALIDATION_ERROR_MESSAGE
    assert secret_detail not in response.get_data(as_text=True)
    assert secret_detail in caplog.text
