# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller workflow specification validation endpoint."""

import logging
from flask import Blueprint, jsonify
from webargs import fields
from webargs.flaskparser import use_kwargs

from reana_workflow_controller.spec_validation import validate_spec_in_sandbox

blueprint = Blueprint("workflows_validation", __name__)
log = logging.getLogger(__name__)

VALIDATION_ERROR_MESSAGE = "Workflow specification validation failed."


@blueprint.route("/workflows/validate", methods=["POST"])
@use_kwargs(
    {
        "bundle_path": fields.Str(required=True),
        "timeout": fields.Int(load_default=None, allow_none=True),
    },
    location="json",
)
def validate_workflow_spec(bundle_path, timeout):  # noqa
    r"""Load a workflow specification in a sandboxed loader Job.

    ---
    post:
      summary: Load a workflow specification in a hardened sandbox.
      description: >-
        Spawns a defense-in-depth Kubernetes Job (the
        reana-workflow-validator image) that loads the raw spec bundle (mounted
        read-only from ``bundle_path`` on the shared volume) and emits the
        resulting serialized specification. The sandbox applies no cluster
        policy; reana-server validates the returned specification itself.
        Network isolation depends on the cluster CNI enforcing NetworkPolicy;
        standard NetworkPolicy cannot isolate the pod from its resident node.
        Returns the sandbox exit code and the loader report.
      operationId: validate_workflow_spec
      consumes:
        - application/json
      produces:
        - application/json
      parameters:
        - name: spec_validation
          in: body
          required: true
          schema:
            type: object
            required: [bundle_path]
            properties:
              bundle_path:
                type: string
                description: Spec bundle path relative to the shared volume root.
              timeout:
                type: integer
                description: Override for the Job activeDeadlineSeconds.
      responses:
        200:
          description: The loader ran; report and exit code are returned.
          schema:
            type: object
            properties:
              exit_code:
                type: integer
              report:
                type: object
        500:
          description: Infrastructure failure running the validation sandbox.
          schema:
            type: object
            properties:
              message:
                type: string
    """
    try:
        exit_code, report = validate_spec_in_sandbox(bundle_path, timeout)
        return jsonify({"exit_code": exit_code, "report": report}), 200
    except Exception:
        # SpecValidationError (sandbox infrastructure failure) and any other
        # unexpected error are both reported as an internal (500) error.
        log.exception("Workflow specification validation failed")
        return jsonify({"message": VALIDATION_ERROR_MESSAGE}), 500
