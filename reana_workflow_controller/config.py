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

SHARED_VOLUME_PATH = os.getenv('SHARED_VOLUME_PATH', '/var/reana')


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

REANA_STORAGE_BACKEND = os.getenv('REANA_STORAGE_BACKEND', 'local')
"""Type of storage attached to the engines, one of ['local', 'cephfs']."""

MANILA_CEPHFS_PVC = 'manila-cephfs-pvc'
"""If CEPH storage backend is used, this represents the name of the
Kubernetes persistent volume claim."""

MOUNT_CVMFS = os.getenv('REANA_MOUNT_CVMFS', False)
"""Option to mount CVMFS volumes in workflow engines and jobs."""

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

WORKFLOW_ENGINE_VERSION = 'cvmfs-16'
"""CWL workflow engine version."""

WORKFLOW_ENGINE_COMMON_ENV_VARS = [
   {
      'name': 'ZMQ_PROXY_CONNECT',
      'value': 'tcp://zeromq-msg-proxy.default.svc.cluster.local:8666'
   },
   {
      'name': 'SHARED_VOLUME_PATH',
      'value': SHARED_VOLUME_PATH
   },
   {
        'name': 'REANA_MOUNT_CVMFS',
        'value': MOUNT_CVMFS
   }
]
"""Common to all workflow engines environment variables."""

WORKFLOW_ENGINE_COMMON_ENV_VARS_DEBUG = ({'name': 'WDB_SOCKET_SERVER',
                                          'value': 'wdb'},
                                         {'name': 'WDB_NO_BROWSER_AUTO_OPEN',
                                          'value': 'True'})
"""Common to all workflow engines environment variables for debug mode."""

TTL_SECONDS_AFTER_FINISHED = 60
"""Threshold in seconds to clean up terminated (either Complete or Failed)
jobs."""


CVMFS_VOLUME_CONFIGURATION = {
   'alice': {
       'name': 'alice-cvmfs-volume',
       'persistentVolumeClaim': {
            'claimName': 'csi-cvmfs-alice-pvc',
            'readOnly': True
       },
       'mountPath': '/cvmfs/alice.cern.ch'
   },
   'cms': {
       'name': 'cms-cvmfs-volume',
       'persistentVolumeClaim': {
            'claimName': 'csi-cvmfs-cms-pvc',
            'readOnly': True
       },
       'mountPath': '/cvmfs/cms.cern.ch'
   },
   'lhcb': {
       'name': 'lhcb-cvmfs-volume',
       'persistentVolumeClaim': {
            'claimName': 'csi-cvmfs-lhcb-pvc',
            'readOnly': True
       },
       'mountPath': '/cvmfs/lhcb.cern.ch'
   },
   'atlas': {
       'name': 'atlas-cvmfs-volume',
       'persistentVolumeClaim': {
            'claimName': 'csi-cvmfs-atlas-pvc',
            'readOnly': True
       },
       'mountPath': '/cvmfs/atlas.cern.ch'
   }
}
