# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller errors."""


class WorkflowNameError(Exception):
    """."""


class REANAWorkflowControllerError(Exception):
    """Error when trying to manage workflows."""


class UploadPathError(Exception):
    """Provided paths contain '../'."""


class WorkflowDeletionError(Exception):
    """Error when trying to delete a workflow."""
