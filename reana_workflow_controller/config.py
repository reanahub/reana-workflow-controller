# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller flask configuration."""

import os

from packaging.version import parse
from reana_workflow_controller.version import __version__

BROKER_URL = os.getenv('RABBIT_MQ_URL',
                       'message-broker.default.svc.cluster.local')

BROKER_USER = os.getenv('RABBIT_MQ_USER', 'test')

BROKER_PASS = os.getenv('RABBIT_MQ_PASS', '1234')

BROKER = os.getenv('RABBIT_MQ', 'amqp://{0}:{1}@{2}//'.format(BROKER_USER,
                                                              BROKER_PASS,
                                                              BROKER_URL))

BROKER_PORT = os.getenv('RABBIT_MQ_PORT', 5672)

SHARED_VOLUME_PATH = os.getenv('SHARED_VOLUME_PATH', '/reana')


SQLALCHEMY_TRACK_MODIFICATIONS = False
"""Track modifications flag."""

DEFAULT_NAME_FOR_WORKFLOWS = 'workflow'
"""The default prefix used to name workflow(s): e.g. reana-1, reana-2, etc.
   If workflow is manually named by the user that prefix will used instead.
"""

WORKFLOW_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
"""Time format for workflow starting time, created time etc."""

EXCHANGE = ''

EXCHANGE_TYPE = ''

STATUS_QUEUE = 'jobs-status'

ROUTING_KEY = 'jobs-status'

PROGRESS_STATUSES = ['running', 'finished', 'failed', 'total']

WORKFLOW_QUEUES = {'cwl': 'cwl-default-queue',
                   'yadage': 'yadage-default-queue',
                   'serial': 'serial-default-queue'}

REANA_STORAGE_BACKEND = os.getenv('REANA_STORAGE_BACKEND', 'local')
"""Type of storage attached to the engines, one of ['local', 'ceph']."""

MANILA_CEPHFS_PVC = 'manila-cephfs-pvc'
"""If CEPH storage backend is used, this represents the name of the
Kubernetes persistent volume claim."""

SHARED_FS_MAPPING = {
    'MOUNT_SOURCE_PATH': os.getenv("SHARED_VOLUME_PATH_ROOT", '/reana'),
    # Root path in the underlying shared file system to be mounted inside
    # workflow engines.
    'MOUNT_DEST_PATH': os.getenv("SHARED_VOLUME_PATH", '/reana'),
    # Mount path for the shared file system volume inside workflow engines.
}
"""Mapping from the shared file system backend to the job file system."""

WORKFLOW_ENGINE_VERSION = parse(__version__).base_version if \
   os.getenv("REANA_DEPLOYMENT_TYPE", 'local') != 'local' else 'latest'
"""CWL workflow engine version."""

TTL_SECONDS_AFTER_FINISHED = 60
"""Threshold in seconds to clean up terminated (either Complete or Failed)
jobs."""
