# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller flask configuration."""

import os
import json

from reana_commons.config import REANA_COMPONENT_PREFIX, SHARED_VOLUME_PATH
from reana_db.models import JobStatus, RunStatus

from reana_workflow_controller.version import __version__


def _env_vars_dict_to_k8s_list(env_vars):
    """Convert env vars stored as a dictionary into a k8s-compatible list."""
    return [{"name": name, "value": str(value)} for name, value in env_vars.items()]


SQLALCHEMY_TRACK_MODIFICATIONS = False
"""Track modifications flag."""

DEFAULT_NAME_FOR_WORKFLOWS = "workflow"
"""The default prefix used to name workflow(s): e.g. reana-1, reana-2, etc.
   If workflow is manually named by the user that prefix will used instead.
"""

PROGRESS_STATUSES = [
    ("running", JobStatus.running),
    ("finished", JobStatus.finished),
    ("failed", JobStatus.failed),
    ("total", None),
]

WORKFLOW_QUEUES = {
    "cwl": "cwl-default-queue",
    "yadage": "yadage-default-queue",
    "serial": "serial-default-queue",
}

SHARED_FS_MAPPING = {
    "MOUNT_SOURCE_PATH": os.getenv("SHARED_VOLUME_PATH_ROOT", SHARED_VOLUME_PATH),
    # Root path in the underlying shared file system to be mounted inside
    # workflow engines.
    "MOUNT_DEST_PATH": os.getenv("SHARED_VOLUME_PATH", SHARED_VOLUME_PATH),
    # Mount path for the shared file system volume inside workflow engines.
}
"""Mapping from the shared file system backend to the job file system."""

PREVIEWABLE_MIME_TYPE_PREFIXES = ["image/", "text/html", "application/pdf"]
"""List of file mime-type prefixes that can be previewed directly from the server."""

REANA_JOB_STATUS_CONSUMER_PREFETCH_COUNT = int(
    os.getenv("REANA_JOB_STATUS_CONSUMER_PREFETCH_COUNT", 10)
)
"""The value defines the max number of unacknowledged deliveries that are
permitted on a ``jobs-status`` consumer."""

REANA_WORKFLOW_ENGINE_IMAGE_CWL = os.getenv(
    "REANA_WORKFLOW_ENGINE_IMAGE_CWL",
    "docker.io/reanahub/reana-workflow-engine-cwl:latest",
)
"""CWL workflow engine version."""

REANA_WORKFLOW_ENGINE_IMAGE_YADAGE = os.getenv(
    "REANA_WORKFLOW_ENGINE_IMAGE_YADAGE",
    "docker.io/reanahub/reana-workflow-engine-yadage:latest",
)
"""Yadage workflow engine version."""

REANA_WORKFLOW_ENGINE_IMAGE_SERIAL = os.getenv(
    "REANA_WORKFLOW_ENGINE_IMAGE_SERIAL",
    "docker.io/reanahub/reana-workflow-engine-serial:latest",
)
"""Serial workflow engine version."""

REANA_WORKFLOW_ENGINE_IMAGE_SNAKEMAKE = os.getenv(
    "REANA_WORKFLOW_ENGINE_IMAGE_SNAKEMAKE",
    "docker.io/reanahub/reana-workflow-engine-snakemake:latest",
)
"""Snakemake workflow engine version."""

REANA_KUBERNETES_JOBS_MEMORY_LIMIT = os.getenv("REANA_KUBERNETES_JOBS_MEMORY_LIMIT")
"""Maximum default memory limit for user job containers. Exceeding this limit will terminate the container.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-memory.
"""

REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT = os.getenv(
    "REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT"
)
"""Maximum custom memory limit that users can assign to their job containers via
``kubernetes_memory_limit`` in reana.yaml. Exceeding this limit will terminate the container.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-memory.
"""

REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT = os.getenv("REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT")
"""Default timeout for user's jobs in seconds. Exceeding this time will terminate the job.

Please see the following URL for more details
https://kubernetes.io/docs/concepts/workloads/controllers/job/#job-termination-and-cleanup.
"""

REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT = os.getenv(
    "REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT"
)
"""Maximum custom timeout in seconds that users can assign to their jobs.

Please see the following URL for more details
https://kubernetes.io/docs/concepts/workloads/controllers/job/#job-termination-and-cleanup.
"""

WORKFLOW_ENGINE_COMMON_ENV_VARS = [
    {"name": "SHARED_VOLUME_PATH", "value": SHARED_VOLUME_PATH}
]
"""Common to all workflow engines environment variables."""


WORKFLOW_ENGINE_CWL_ENV_VARS = _env_vars_dict_to_k8s_list(
    json.loads(os.getenv("REANA_WORKFLOW_ENGINE_CWL_ENV_VARS", "{}"))
)
"""Environment variables to be passed to the CWL workflow engine container."""

WORKFLOW_ENGINE_SERIAL_ENV_VARS = _env_vars_dict_to_k8s_list(
    json.loads(os.getenv("REANA_WORKFLOW_ENGINE_SERIAL_ENV_VARS", "{}"))
)
"""Environment variables to be passed to the serial workflow engine container."""

WORKFLOW_ENGINE_SNAKEMAKE_ENV_VARS = _env_vars_dict_to_k8s_list(
    json.loads(os.getenv("REANA_WORKFLOW_ENGINE_SNAKEMAKE_ENV_VARS", "{}"))
)
"""Environment variables to be passed to the Snakemake workflow engine container."""

WORKFLOW_ENGINE_YADAGE_ENV_VARS = _env_vars_dict_to_k8s_list(
    json.loads(os.getenv("REANA_WORKFLOW_ENGINE_YADAGE_ENV_VARS", "{}"))
)
"""Environment variables to be passed to the Yadage workflow engine container."""

DEBUG_ENV_VARS = (
    {
        "name": "WDB_SOCKET_SERVER",
        "value": os.getenv("WDB_SOCKET_SERVER", f"{REANA_COMPONENT_PREFIX}-wdb"),
    },
    {"name": "WDB_NO_BROWSER_AUTO_OPEN", "value": "True"},
    {"name": "FLASK_ENV", "value": "development"},
)
"""Common to all workflow engines environment variables for debug mode."""

REANA_OPENSEARCH_ENABLED = (
    os.getenv("REANA_OPENSEARCH_ENABLED", "false").lower() == "true"
)
"""OpenSearch enabled flag."""

REANA_OPENSEARCH_HOST = os.getenv(
    "REANA_OPENSEARCH_HOST", "opensearch-cluster-master.default.svc.cluster.local"
)
"""OpenSearch host."""

REANA_OPENSEARCH_PORT = os.getenv("REANA_OPENSEARCH_PORT", "9200")
"""OpenSearch port."""

REANA_OPENSEARCH_URL_PREFIX = os.getenv("REANA_OPENSEARCH_URL_PREFIX", "")
"""OpenSearch URL prefix."""

REANA_OPENSEARCH_USER = os.getenv("REANA_OPENSEARCH_USER", "admin")
"""OpenSearch user."""

REANA_OPENSEARCH_PASSWORD = os.getenv("REANA_OPENSEARCH_PASSWORD", "admin")
"""OpenSearch password."""

REANA_OPENSEARCH_USE_SSL = (
    os.getenv("REANA_OPENSEARCH_USE_SSL", "false").lower() == "true"
)
"""OpenSearch SSL flag."""

REANA_OPENSEARCH_CA_CERTS = os.getenv("REANA_OPENSEARCH_CA_CERTS")
"""OpenSearch CA certificates."""


def _parse_interactive_sessions_environments(env_var):
    config = {}
    for type_ in env_var:
        recommended = []
        env_recommended = env_var[type_].get("recommended") or []
        for recommended_item in env_recommended:
            image = recommended_item.get("image")
            if not image:
                continue
            name = recommended_item.get("name") or image
            recommended.append({"name": name, "image": image})

        config[type_] = {
            "allow_custom": env_var[type_].get("allow_custom", False),
            "recommended": recommended,
        }
    return config


REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS = _parse_interactive_sessions_environments(
    json.loads(os.getenv("REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS", "{}"))
)
"""Allowed and recommended environments to be used for interactive sessions.

This is a dictionary where keys are the type of the interactive session.
For each session type, a list of recommended Docker images are provided (`recommended`)
and whether custom images are allowed (`allow_custom`).

Example:
{
    "jupyter": {
        "recommended": [
            {
                "name": "Jupyter SciPy Notebook 6.4.5",
                "image": "docker.io/jupyter/scipy-notebook:notebook-6.4.5"
            }
        ],
        "allow_custom": true
    }
}
"""

REANA_INTERACTIVE_SESSIONS_RECOMMENDED_IMAGES = {
    type_: {recommended["image"] for recommended in config["recommended"]}
    for type_, config in REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS.items()
}
"""Set of recommended images for each interactive session type."""

REANA_INTERACTIVE_SESSIONS_DEFAULT_IMAGES = {
    type_: next(iter(config["recommended"]), {}).get("image")
    for type_, config in REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS.items()
}
"""Default image for each interactive session type, can be `None`."""

JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT = 8888
"""Default port for Jupyter based interactive session deployments."""

JOB_CONTROLLER_IMAGE = os.getenv(
    "REANA_JOB_CONTROLLER_IMAGE", "docker.io/reanahub/reana-job-controller:latest"
)
"""Default image for REANA Job Controller sidecar."""


JOB_CONTROLLER_ENV_VARS = _env_vars_dict_to_k8s_list(
    json.loads(os.getenv("REANA_JOB_CONTROLLER_ENV_VARS", "{}"))
)
"""Environment variables to be passed to the job controller container."""

JOB_CONTROLLER_CONTAINER_PORT = 5000
"""Default container port for REANA Job Controller sidecar."""

JOB_CONTROLLER_SHUTDOWN_ENDPOINT = "/shutdown"
"""Endpoint of reana-job-controller used to stop all the jobs."""

JOB_CONTROLLER_NAME = "job-controller"
"""Default job controller container name."""

WORKFLOW_ENGINE_NAME = "workflow-engine"
"""Default workflow engine container name."""

REANA_GITLAB_HOST = os.getenv("REANA_GITLAB_HOST", "CHANGE_ME")
"""GitLab API HOST"""

REANA_GITLAB_URL = "https://{}".format(REANA_GITLAB_HOST)
"""GitLab API URL"""

REANA_HOSTNAME = os.getenv("REANA_HOSTNAME", "CHANGE_ME")
"""REANA URL"""

REANA_INGRESS_ANNOTATIONS = json.loads(os.getenv("REANA_INGRESS_ANNOTATIONS", "{}"))
"""REANA Ingress annotations defined by the administrator."""

REANA_INGRESS_CLASS_NAME = os.getenv("REANA_INGRESS_CLASS_NAME")
"""REANA Ingress class name defined by the administrator to be used for interactive sessions."""

REANA_INGRESS_HOST = os.getenv("REANA_INGRESS_HOST", "")
"""REANA Ingress host defined by the administrator."""

IMAGE_PULL_SECRETS = os.getenv("IMAGE_PULL_SECRETS", "").split(",")
"""Docker image pull secrets which allow the usage of private images."""


ALIVE_STATUSES = [
    RunStatus.created,
    RunStatus.running,
    RunStatus.queued,
    RunStatus.pending,
]
"""Alive workflow statuses."""

REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD = int(
    os.getenv("REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD", "120")
)
"""Grace period before terminating the job controller and workflow engine pod.

The job controller needs to clean up all the running jobs before the end of the grace period.
"""

CONTAINER_IMAGE_ALIAS_PREFIXES = ["docker.io/", "docker.io/library/", "library/"]
"""Prefixes that can be removed from container image references to generate valid image aliases."""

MAX_WORKFLOW_SHARING_MESSAGE_LENGTH = 5000
"""Maximum length of the user-provided message when sharing a workflow."""
