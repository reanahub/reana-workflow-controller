# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Rest API endpoint for workflow management."""

from __future__ import absolute_import

import logging

from flask import Flask, jsonify
from marshmallow.exceptions import ValidationError
from reana_commons.config import REANA_LOG_FORMAT, REANA_LOG_LEVEL
from reana_db.database import Session
from werkzeug.exceptions import UnprocessableEntity


from reana_db.models import Base  # isort:skip  # noqa


def handle_args_validation_error(error: UnprocessableEntity):
    """Error handler for werkzeug exception ``UnprocessableEntity``.

    This error handler is needed to display useful error messages, instead of the
    generic default one, when marshmallow argument validation fails.
    """
    error_message = error.description or str(error)

    exception = getattr(error, "exc", None)
    if isinstance(exception, ValidationError):
        validation_messages = []
        # this is slightly different from r-server error handler due to different
        # versions of webargs/marshmallow
        # the format of normalized_messages() is:
        # {"json": {"field name": ["error 1", "error 2"]}}
        for field_messages in exception.normalized_messages().values():
            for field, messages in field_messages.items():
                validation_messages.append(
                    "Field '{}': {}".format(field, ", ".join(messages))
                )
        error_message = ". ".join(validation_messages)

    return jsonify({"message": error_message}), 400


def create_app(config_mapping=None):
    """REANA Workflow Controller application factory."""
    logging.basicConfig(level=REANA_LOG_LEVEL, format=REANA_LOG_FORMAT)
    app = Flask(__name__)
    app.config.from_object("reana_workflow_controller.config")
    if config_mapping:
        app.config.from_mapping(config_mapping)

    app.secret_key = "super secret key"
    # Register API routes
    from reana_workflow_controller.rest import (
        workflows_session,
        workflows_status,
        workflows_workspace,
        workflows,
    )  # noqa

    app.register_blueprint(workflows_session.blueprint, url_prefix="/api")
    app.register_blueprint(workflows.blueprint, url_prefix="/api")
    app.register_blueprint(workflows_status.blueprint, url_prefix="/api")
    app.register_blueprint(workflows_workspace.blueprint, url_prefix="/api")

    app.register_error_handler(UnprocessableEntity, handle_args_validation_error)

    app.session = Session
    return app
