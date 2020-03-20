# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller flask configuration."""

import os

from packaging.version import parse
from reana_commons.config import SHARED_VOLUME_PATH

from reana_workflow_controller.version import __version__

SQLALCHEMY_TRACK_MODIFICATIONS = False
"""Track modifications flag."""

DEFAULT_NAME_FOR_WORKFLOWS = 'workflow'
"""The default prefix used to name workflow(s): e.g. reana-1, reana-2, etc.
   If workflow is manually named by the user that prefix will used instead.
"""

WORKFLOW_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
"""Time format for workflow starting time, created time etc."""

PROGRESS_STATUSES = ['running', 'finished', 'failed', 'total']

WORKFLOW_QUEUES = {'cwl': 'cwl-default-queue',
                   'yadage': 'yadage-default-queue',
                   'serial': 'serial-default-queue'}

SHARED_FS_MAPPING = {
    'MOUNT_SOURCE_PATH': os.getenv("SHARED_VOLUME_PATH_ROOT",
                                   SHARED_VOLUME_PATH),
    # Root path in the underlying shared file system to be mounted inside
    # workflow engines.
    'MOUNT_DEST_PATH': os.getenv("SHARED_VOLUME_PATH",
                                 SHARED_VOLUME_PATH),
    # Mount path for the shared file system volume inside workflow engines.
}
"""Mapping from the shared file system backend to the job file system."""

REANA_WORKFLOW_ENGINE_IMAGE_CWL = os.getenv(
     'REANA_WORKFLOW_ENGINE_IMAGE_CWL',
     'reanahub/reana-workflow-engine-cwl:latest')
"""CWL workflow engine version."""

REANA_WORKFLOW_ENGINE_IMAGE_YADAGE = os.getenv(
     'REANA_WORKFLOW_ENGINE_IMAGE_YADAGE',
     'reanahub/reana-workflow-engine-yadage:latest')
"""Yadage workflow engine version."""

REANA_WORKFLOW_ENGINE_IMAGE_SERIAL = os.getenv(
     'REANA_WORKFLOW_ENGINE_IMAGE_SERIAL',
     'reanahub/reana-workflow-engine-serial:latest')
"""Serial workflow engine version."""

WORKFLOW_ENGINE_COMMON_ENV_VARS = [
   {
      'name': 'SHARED_VOLUME_PATH',
      'value': SHARED_VOLUME_PATH
   }
]
"""Common to all workflow engines environment variables."""

DEBUG_ENV_VARS = ({'name': 'WDB_SOCKET_SERVER',
                   'value': 'reana-wdb'},
                  {'name': 'WDB_NO_BROWSER_AUTO_OPEN',
                   'value': 'True'},
                  {'name': 'FLASK_ENV',
                   'value': 'development'})
"""Common to all workflow engines environment variables for debug mode."""

TTL_SECONDS_AFTER_FINISHED = 60
"""Threshold in seconds to clean up terminated (either Complete or Failed)
jobs."""

JUPYTER_INTERACTIVE_SESSION_DEFAULT_IMAGE = "jupyter/scipy-notebook"
"""Default image for Jupyter based interactive session deployments."""

JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT = 8888
"""Default port for Jupyter based interactive session deployments."""

JOB_CONTROLLER_IMAGE = os.getenv(
    'REANA_JOB_CONTROLLER_IMAGE',
    'reanahub/reana-job-controller:latest')
"""Default image for REANA Job Controller sidecar."""

JOB_CONTROLLER_CONTAINER_PORT = 5000
"""Default container port for REANA Job Controller sidecar."""

JOB_CONTROLLER_NAME = 'job-controller'
"""Default job controller container name."""

WORKFLOW_ENGINE_NAME = 'workflow-engine'
"""Default workflow engine container name."""

REANA_GITLAB_HOST = os.getenv('REANA_GITLAB_HOST', 'CHANGE_ME')
"""GitLab API HOST"""

REANA_GITLAB_URL = 'https://{}'.format(REANA_GITLAB_HOST)
"""GitLab API URL"""

REANA_URL = os.getenv('REANA_URL', 'CHANGE_ME')
"""REANA URL"""

IMAGE_PULL_SECRETS = os.getenv('IMAGE_PULL_SECRETS', '').split(',')
"""Docker image pull secrets which allow the usage of private images."""
