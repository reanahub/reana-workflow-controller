# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller Instance."""

import threading

from flask import current_app

from reana_workflow_controller.factory import create_app

app = create_app()


@app.teardown_appcontext
def shutdown_session(response_or_exc):
    """Close session on app teardown."""
    current_app.session.remove()
    return response_or_exc


if __name__ == "__main__":
    app.run(host="0.0.0.0")
