# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller errors."""


def user_id_does_not_exist(user_id):
    """Return the error message for a user ID that does not exist."""
    return f"User with id '{user_id}' does not exist."


def user_email_does_not_exist(user_email):
    """Return the error message for a user email that does not exist."""
    return f"User with email '{user_email}' does not exist."


def workflow_already_shared(workflow_name, user_email):
    """Return the error message for a workflow that is already shared."""
    return f"{workflow_name} is already shared with {user_email}."


def workflow_not_shared(workflow_name, user_email):
    """Return the error message for a workflow that is not shared."""
    return f"{workflow_name} is not shared with {user_email}."


def workflow_share_with_self():
    """Return the error message for sharing a workflow with oneself."""
    return "Unable to share a workflow with yourself."


def workflow_unshare_with_self():
    """Return the error message for unsharing a workflow with oneself."""
    return "Unable to unshare a workflow with yourself."


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


class REANAWorkflowStatusError(Exception):
    """Error when trying to change workflow status."""


class REANAWorkflowStopError(Exception):
    """Error when trying to stop a workflow."""
