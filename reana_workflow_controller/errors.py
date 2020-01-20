# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
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


class REANAExternalCallError(Exception):
    """Error when connecting to an external service."""
