# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller errors."""


class REANAWorkflowNameError(Exception):
    """."""


class REANAWorkflowControllerError(Exception):
    """Error when trying to manage workflows."""


class REANAUploadPathError(Exception):
    """Provided paths contain '../'."""


class REANAWorkflowDeletionError(Exception):
    """Error when trying to delete a workflow."""


class REANAInteractiveSessionError(Exception):
    """Error when trying to create an interactive session."""


class ReservedEnvironmentVariableError(REANAInteractiveSessionError):
    """User-supplied env var name collides with a controller-reserved name.

    A user-input error, not a server/infra failure like most other
    ``REANAInteractiveSessionError`` raise sites — kept as a distinct
    subclass so the REST layer can map it to 4xx instead of the generic
    500 the base class still gets everywhere else.
    """


class REANAExternalCallError(Exception):
    """Error when connecting to an external service."""


class REANAWorkflowStatusError(Exception):
    """Error when trying to change workflow status."""


class REANAWorkflowStopError(Exception):
    """Error when trying to stop a workflow."""
