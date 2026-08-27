# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller flask configuration."""

import os
import json

from reana_commons.config import (
    MQ_CONNECTION_STRING,
    REANA_COMPONENT_PREFIX,
    SHARED_VOLUME_PATH,
)
from reana_db.models import JobStatus, RunStatus
from distutils.util import strtobool
from typing import List

from reana_workflow_controller.version import __version__


def _env_vars_dict_to_k8s_list(env_vars):
    """Convert env vars stored as a dictionary into a k8s-compatible list."""
    return [{"name": name, "value": str(value)} for name, value in env_vars.items()]


def compose_reana_url(hostname: str, hostport: str | int) -> str:
    """
    Compose a REANA API URL while omitting the default HTTPS port (443).

    Args:
        hostname (str): The REANA hostname.
        hostport (str | int): The REANA host port.

    Returns:
        str: The full base URL.
    """
    if str(hostport) == "443":
        return f"https://{hostname}"
    return f"https://{hostname}:{hostport}"


SECRET_KEY = os.getenv("REANA_SECRET_KEY", "")
"""Secret key used for the application user sessions."""

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

REANA_KUBERNETES_JOBS_CPU_REQUEST = os.getenv(
    "REANA_KUBERNETES_JOBS_CPU_REQUEST")
"""Default CPU request for user job containers.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-cpu.
"""

REANA_KUBERNETES_JOBS_CPU_LIMIT = os.getenv("REANA_KUBERNETES_JOBS_CPU_LIMIT")
"""Default CPU limit for user job containers.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-cpu.
"""

REANA_KUBERNETES_JOBS_MEMORY_REQUEST = os.getenv(
    "REANA_KUBERNETES_JOBS_MEMORY_REQUEST")
"""Default memory request for user job containers.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-memory.
"""

REANA_KUBERNETES_JOBS_MEMORY_LIMIT = os.getenv(
    "REANA_KUBERNETES_JOBS_MEMORY_LIMIT")
"""Default memory limit for user job containers. Exceeding this limit will terminate the container.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-memory.
"""

REANA_KUBERNETES_JOBS_MAX_USER_CPU_REQUEST = os.getenv(
    "REANA_KUBERNETES_JOBS_MAX_USER_CPU_REQUEST"
)
"""Maximum custom CPU request that users can assign to their job containers via
``kubernetes_cpu_request`` in reana.yaml.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-cpu.
"""

REANA_KUBERNETES_JOBS_MAX_USER_CPU_LIMIT = os.getenv(
    "REANA_KUBERNETES_JOBS_MAX_USER_CPU_LIMIT"
)
"""Maximum custom CPU limit that users can assign to their job containers via
``kubernetes_cpu_limit`` in reana.yaml. Exceeding this limit will terminate the container.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-cpu.
"""

REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_REQUEST = os.getenv(
    "REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_REQUEST"
)
"""Maximum custom memory request that users can assign to their job containers via
``kubernetes_memory_request`` in reana.yaml.

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

REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT = os.getenv(
    "REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT")
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

REANA_KUBERNETES_JOBS_MIN_USER_UID = os.getenv(
    "REANA_KUBERNETES_JOBS_MIN_USER_UID")
"""Minimum accepted user runtime container UID that users can assign to their job
containers via ``kubernetes_uid`` in ``reana.yaml``. Jobs requesting a smaller
UID are refused at submission time with a clear error message. Forwarded to
reana-job-controller via the job batch pod environment.
"""

WORKFLOW_ENGINE_COMMON_ENV_VARS = [
    {"name": "SHARED_VOLUME_PATH", "value": SHARED_VOLUME_PATH},
    {"name": "RABBIT_MQ", "value": MQ_CONNECTION_STRING},
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
    {"name": "FLASK_DEBUG", "value": "1"},
)
"""Common to all workflow engines environment variables for debug mode."""

REANA_OPENSEARCH_ENABLED = (
    os.getenv("REANA_OPENSEARCH_ENABLED", "false").lower() == "true"
)
"""OpenSearch enabled flag."""

REANA_OPENSEARCH_HOST = os.getenv(
    "REANA_OPENSEARCH_HOST", "reana-opensearch-master")
"""OpenSearch host."""

REANA_OPENSEARCH_PORT = os.getenv("REANA_OPENSEARCH_PORT", "9200")
"""OpenSearch port."""

REANA_OPENSEARCH_URL_PREFIX = os.getenv("REANA_OPENSEARCH_URL_PREFIX", "")
"""OpenSearch URL prefix."""

REANA_OPENSEARCH_USER = os.getenv("REANA_OPENSEARCH_USER", "")
"""OpenSearch user."""

REANA_OPENSEARCH_PASSWORD = os.getenv("REANA_OPENSEARCH_PASSWORD", "")
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
                "name": "Jupyter SciPy Notebook 7.2.2",
                "image": "docker.io/jupyter/scipy-notebook:notebook-7.2.2"
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

REANA_JOB_CONTROLLER_SECRET = os.getenv("REANA_JOB_CONTROLLER_SECRET")
"""DOptional secret for REANA Job Controller sidecar."""

JOB_CONTROLLER_ENV_VARS = _env_vars_dict_to_k8s_list(
    json.loads(os.getenv("REANA_JOB_CONTROLLER_ENV_VARS", "{}"))
)
"""Environment variables to be passed to the job controller container."""


REANA_WORKFLOW_VALIDATOR_IMAGE = os.getenv(
    "REANA_WORKFLOW_VALIDATOR_IMAGE",
    "docker.io/reanahub/reana-workflow-validator:latest",
)
"""Image for the sandboxed workflow specification loader (loads untrusted
workflow specs in a locked-down Job)."""


_SPEC_VALIDATION_RESERVED_ENV_VAR_NAMES = frozenset(
    {
        # The controller owns the loader's filesystem contract.
        "REANA_VALIDATION_INPUT_DIR",
        "REANA_VALIDATION_WORK_DIR",
        "HOME",
        "TMPDIR",
        # Interpreter and shell startup hooks can execute operator-provided code
        # before the validator starts.
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "BASH_ENV",
        "ENV",
        "GCONV_PATH",
        "HOSTALIASES",
        "SHELLOPTS",
    }
)


def _parse_spec_validation_env_vars(raw_env_vars):
    """Parse and validate environment variables for validator Jobs.

    The validator loads untrusted workflow code. The configured values are
    therefore deliberately treated as non-secret, and variables that could
    alter the loader's filesystem contract or interpreter startup are rejected.
    """
    env_vars = json.loads(raw_env_vars)
    if not isinstance(env_vars, dict):
        raise ValueError("REANA_WORKFLOW_VALIDATOR_ENV_VARS must be a JSON object.")

    invalid_names = sorted(
        name
        for name in env_vars
        if name in _SPEC_VALIDATION_RESERVED_ENV_VAR_NAMES or name.startswith("LD_")
    )
    if invalid_names:
        raise ValueError(
            "Reserved validator environment variable(s): {}.".format(
                ", ".join(invalid_names)
            )
        )
    return _env_vars_dict_to_k8s_list(env_vars)


REANA_WORKFLOW_VALIDATOR_ENV_VARS = _parse_spec_validation_env_vars(
    os.getenv("REANA_WORKFLOW_VALIDATOR_ENV_VARS", "{}")
)
"""Non-secret environment variables passed to sandboxed validator Jobs."""


SPEC_VALIDATION_TIMEOUT = int(os.getenv("REANA_SPEC_VALIDATION_TIMEOUT", "60"))
"""Hard wall-clock limit in seconds (activeDeadlineSeconds) for a sandboxed spec
validation Job. Kills spec loads that hang (e.g. an infinite-loop Snakefile).
The deadline counts from pod start (including any image pull), and loading a
workflow that resolves remote references over the public internet (a yadage
``toplevel`` git clone, a chain of CWL ``$import``s) can take a while, so the
default is generous; operators running such workflows can raise it further via
the ``REANA_SPEC_VALIDATION_TIMEOUT`` environment variable."""

SPEC_VALIDATION_MAX_TIMEOUT = int(
    os.getenv("REANA_SPEC_VALIDATION_MAX_TIMEOUT", str(SPEC_VALIDATION_TIMEOUT * 10))
)
"""Upper bound (seconds) for a caller-supplied validation ``timeout`` override.
A per-request ``timeout`` is clamped to ``[1, SPEC_VALIDATION_MAX_TIMEOUT]`` so a
caller cannot request an arbitrarily long-lived (worker-occupying) Job or pass a
non-positive value that Kubernetes would reject with a confusing error."""

SPEC_VALIDATION_LOG_TAIL_LINES = int(
    os.getenv("REANA_SPEC_VALIDATION_LOG_TAIL_LINES", "500")
)
"""How many trailing log lines to read from a finished validator pod. The
validator report is emitted last, so it always lives within this tail.
Configurable via ``REANA_SPEC_VALIDATION_LOG_TAIL_LINES``."""

SPEC_VALIDATION_LOG_LIMIT_BYTES = int(
    os.getenv("REANA_SPEC_VALIDATION_LOG_LIMIT_BYTES", str(100 * 1024 * 1024))
)
"""Maximum bytes to read from a finished validator pod log. The loader runs
untrusted workflow code, so Kubernetes log retrieval must have a byte cap even
when a malicious spec prints a single huge line. Configurable via
``REANA_SPEC_VALIDATION_LOG_LIMIT_BYTES``."""

SPEC_VALIDATION_POLL_INTERVAL = float(
    os.getenv("REANA_SPEC_VALIDATION_POLL_INTERVAL", "2")
)
"""How often (seconds) to poll the validation Job for completion."""

SPEC_VALIDATION_CPU_LIMIT = os.getenv("REANA_SPEC_VALIDATION_CPU_LIMIT", "1")
"""CPU limit for the sandboxed spec validation container."""

SPEC_VALIDATION_MEMORY_LIMIT = os.getenv("REANA_SPEC_VALIDATION_MEMORY_LIMIT", "1Gi")
"""Memory limit for the sandboxed spec validation container (bounds spec loads
that try to exhaust memory)."""

SPEC_VALIDATION_EPHEMERAL_STORAGE_REQUEST = os.getenv(
    "REANA_SPEC_VALIDATION_EPHEMERAL_STORAGE_REQUEST", "128Mi"
)
"""Ephemeral-storage request for sandboxed specification validation."""

SPEC_VALIDATION_EPHEMERAL_STORAGE_LIMIT = os.getenv(
    "REANA_SPEC_VALIDATION_EPHEMERAL_STORAGE_LIMIT", "1Gi"
)
"""Combined scratch-volume and container ephemeral-storage limit."""

SPEC_VALIDATION_MAX_FILES = int(os.getenv("REANA_SPEC_BUNDLE_MAX_FILES", "1000"))
"""Maximum number of files copied into validator scratch storage."""

SPEC_VALIDATION_MAX_BYTES = int(
    os.getenv("REANA_SPEC_BUNDLE_MAX_BYTES", str(100 * 1024 * 1024))
)
"""Maximum number of bundle bytes copied into validator scratch storage."""

SPEC_VALIDATION_ALLOW_EGRESS = os.getenv(
    "REANA_SPEC_VALIDATION_ALLOW_EGRESS", "true"
).lower() in ("true", "1", "yes", "on")
"""Whether the sandboxed spec validator may reach the *public* network.

Defaults to ``true`` so that workflows referencing remote resources (e.g. a
remote yadage ``toplevel`` or CWL ``$import``) can still be loaded/validated.
Set to ``false`` to create a policy with no egress allow rules. Regardless of
this flag, the NetworkPolicy requests that configured cluster-internal ranges
remain blocked (see ``SPEC_VALIDATION_BLOCKED_EGRESS_CIDRS``). Enforcement
requires a NetworkPolicy-capable CNI; applicable policies are additive, and
standard NetworkPolicy does not block traffic to the pod's resident node."""

SPEC_VALIDATION_BLOCKED_EGRESS_CIDRS = [
    cidr.strip()
    for cidr in os.getenv(
        "REANA_SPEC_VALIDATION_BLOCKED_EGRESS_CIDRS",
        "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,100.64.0.0/10",
    ).split(",")
    if cidr.strip()
]
"""Egress destination CIDRs excluded from the validator's public-egress rule.
Defaults to the private/cluster-internal ranges (pods, services, nodes) plus the
link-local range (which covers the cloud instance-metadata endpoint
``169.254.169.254``). Operators on clusters with a different pod/service CIDR
can extend this list. The exclusion is enforced by the cluster CNI and is
subject to standard NetworkPolicy limitations, including additive policies and
resident-node traffic."""

SPEC_VALIDATION_DNS_NAMESERVERS = [
    server.strip()
    for server in os.getenv(
        "REANA_SPEC_VALIDATION_DNS_NAMESERVERS", "1.1.1.1,8.8.8.8"
    ).split(",")
    if server.strip()
]
"""Public DNS resolvers the validator pod uses when egress is allowed.

The cluster DNS (kube-dns) normally lives in one of the excluded internal
ranges, so the validator uses these public resolvers when egress is enabled
(``dnsPolicy: None``). This avoids intentionally allowing cluster DNS while
still letting remote ``$import``/``toplevel`` hostnames resolve; actual traffic
isolation depends on the cluster's NetworkPolicy enforcement."""

JOB_CONTROLLER_CONTAINER_PORT = 5000
"""Default container port for REANA Job Controller sidecar."""

JOB_CONTROLLER_SHUTDOWN_ENDPOINT = "/shutdown"
"""Endpoint of reana-job-controller used to stop all the jobs."""

JOB_CONTROLLER_NAME = "job-controller"
"""Default job controller container name."""

WORKFLOW_ENGINE_NAME = "workflow-engine"
"""Default workflow engine container name."""

REANA_GITLAB_HOST = os.getenv("REANA_GITLAB_HOST", "")
"""GitLab API HOST"""

REANA_GITLAB_URL = "https://{}".format(
    REANA_GITLAB_HOST) if REANA_GITLAB_HOST else ""
"""GitLab API URL, empty when GitLab is not configured."""

REANA_HOSTNAME = os.getenv("REANA_HOSTNAME", "localhost")
"""REANA host name."""

REANA_HOSTPORT = os.getenv("REANA_HOSTPORT", "30443")
"""REANA host name port number."""

REANA_URL = compose_reana_url(REANA_HOSTNAME, REANA_HOSTPORT)
"""REANA URL."""

REANA_INGRESS_ANNOTATIONS = json.loads(
    os.getenv("REANA_INGRESS_ANNOTATIONS", "{}"))
"""REANA Ingress annotations defined by the administrator."""

REANA_INGRESS_CLASS_NAME = os.getenv("REANA_INGRESS_CLASS_NAME")
"""REANA Ingress class name defined by the administrator to be used for interactive sessions."""

REANA_INGRESS_HOST = os.getenv("REANA_INGRESS_HOST", "")
"""REANA Ingress host defined by the administrator."""

IMAGE_PULL_SECRETS = os.getenv("IMAGE_PULL_SECRETS", "").split(",")
"""Docker image pull secrets which allow the usage of private images."""

TRAEFIK_ENABLED = os.getenv("TRAEFIK_ENABLED", "true").lower() == "true"
"""Whether Traefik is enabled in the cluster or not."""

TRAEFIK_EXTERNAL = os.getenv("TRAEFIK_EXTERNAL", "false").lower() == "true"
"""Whether Traefik is deployed externally or not."""

DASK_ENABLED = os.getenv("DASK_ENABLED", "true").lower() == "true"
"""Whether Dask is enabled in the cluster or not."""

DASK_AUTOSCALER_ENABLED = os.getenv(
    "DASK_AUTOSCALER_ENABLED", "true").lower() == "true"
"""Whether Dask autoscaler is enabled in the cluster or not."""

REANA_DASK_CLUSTER_MAX_MEMORY_LIMIT = os.getenv(
    "REANA_DASK_CLUSTER_MAX_MEMORY_LIMIT", "16Gi"
)
"""Maximum memory limit for Dask clusters."""

REANA_DASK_CLUSTER_DEFAULT_NUMBER_OF_WORKERS = int(
    os.getenv("REANA_DASK_CLUSTER_DEFAULT_NUMBER_OF_WORKERS", 2)
)
"""Number of workers in Dask cluster by default."""

REANA_DASK_CLUSTER_DEFAULT_SINGLE_WORKER_MEMORY = os.getenv(
    "REANA_DASK_CLUSTER_DEFAULT_SINGLE_WORKER_MEMORY", "2Gi"
)
"""Memory for one Dask worker by default."""

REANA_DASK_CLUSTER_MAX_SINGLE_WORKER_MEMORY = os.getenv(
    "REANA_DASK_CLUSTER_MAX_SINGLE_WORKER_MEMORY", "8Gi"
)
"""Maximum memory for one Dask worker."""

REANA_DASK_CLUSTER_DEFAULT_SINGLE_WORKER_THREADS = int(
    os.getenv("REANA_DASK_CLUSTER_DEFAULT_SINGLE_WORKER_THREADS", 4)
)
"""Number of threads for one Dask worker by default."""

VOMSPROXY_CONTAINER_IMAGE = os.getenv(
    "VOMSPROXY_CONTAINER_IMAGE", "docker.io/reanahub/reana-auth-vomsproxy:1.3.1"
)
"""Default docker image of VOMSPROXY sidecar container."""

VOMSPROXY_CONTAINER_NAME = "voms-proxy"
"""Name of VOMSPROXY sidecar container."""

VOMSPROXY_CERT_CACHE_LOCATION = "/vomsproxy_cache/"
"""Directory of voms-proxy certificate cache.

This directory is shared between job & VOMSPROXY container."""

VOMSPROXY_CERT_CACHE_FILENAME = "x509up_proxy"
"""Name of the voms-proxy certificate cache file."""

RUCIO_CONTAINER_IMAGE = os.getenv(
    "RUCIO_CONTAINER_IMAGE", "docker.io/reanahub/reana-auth-rucio:1.1.1"
)
"""Default docker image of RUCIO sidecar container."""

RUCIO_CONTAINER_NAME = "reana-auth-rucio"
"""Name of RUCIO sidecar container."""

RUCIO_CACHE_LOCATION = "/rucio_cache/"
"""Directory of Rucio cache.

This directory is shared between job & Rucio container."""

RUCIO_CFG_CACHE_FILENAME = "rucio.cfg"
"""Name of the RUCIO configuration cache file."""

RUCIO_CERN_BUNDLE_CACHE_FILENAME = "CERN-bundle.pem"
"""Name of the CERN Bundle cache file."""

ALIVE_STATUSES = [
    RunStatus.created,
    RunStatus.running,
    RunStatus.queued,
    RunStatus.pending,
]
"""Alive workflow statuses."""

KUEUE_ENABLED = bool(strtobool(os.getenv("KUEUE_ENABLED", "False")))
"""Whether to use Kueue for workflow scheduling."""

KUEUE_LOCAL_QUEUE_NAME = "local-queue-batch"
"""Name of the local queue to be used by Kueue."""

REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD = int(
    os.getenv("REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD", "120")
)
"""Grace period before terminating the job controller and workflow engine pod.

The job controller needs to clean up all the running jobs before the end of the grace period.
"""

CONTAINER_IMAGE_ALIAS_PREFIXES = [
    "docker.io/", "docker.io/library/", "library/"]
"""Prefixes that can be removed from container image references to generate valid image aliases."""

MAX_WORKFLOW_SHARING_MESSAGE_LENGTH = 5000
"""Maximum length of the user-provided message when sharing a workflow."""


REANA_RUNTIME_JOBS_KUBERNETES_TOLERATIONS = os.getenv(
    "REANA_RUNTIME_JOBS_KUBERNETES_TOLERATIONS"
)
"""Tolerations for jobs"""
REANA_DATASTORE_ENABLED = os.getenv("REANA_DATASTORE_ENABLED") == "true"
"""Set datastore (s3) sidecar for interactive sessions enabled or disabled"""

if REANA_DATASTORE_ENABLED:
    REANA_DATASTORE_IMAGE = os.getenv("REANA_DATASTORE_IMAGE")
    """Optional Image for datastore (s3) sidecar for interactive sessions"""

    REANA_DATASTORE_SECRET = os.getenv("REANA_DATASTORE_SECRET")
    """Optional secret for datastore (s3) sidecar for interactive sessions"""
else:
    REANA_DATASTORE_IMAGE = ""
    REANA_DATASTORE_SECRET = ""


def _parse_comma_separated_list(value: str) -> List[str]:
    """Parse comma-separated env var values into a list of strings."""
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


_VALID_RUNTIME_FS_GROUP_CHANGE_POLICIES = {"Always", "OnRootMismatch"}
"""Valid REANA runtime pod fsGroup change policy values."""


def _parse_runtime_fs_group_change_policy(value: str | None) -> str:
    """Parse runtime pod fsGroup change policy configuration."""
    policy = (value or "").strip()
    if not policy:
        return "OnRootMismatch"
    if policy not in _VALID_RUNTIME_FS_GROUP_CHANGE_POLICIES:
        valid_values = ", ".join(
            sorted(_VALID_RUNTIME_FS_GROUP_CHANGE_POLICIES))
        raise ValueError(
            "Invalid REANA_RUNTIME_FS_GROUP_CHANGE_POLICY value: "
            f"{policy}. Valid values: {valid_values}"
        )
    return policy


def _parse_runtime_sessions_supplemental_groups(value: str | None) -> List[int]:
    """Parse supplemental groups for runtime interactive-session pods."""
    raw_groups = "100" if value is None else value
    parsed_groups = []
    for group_value in _parse_comma_separated_list(raw_groups):
        try:
            group_id = int(group_value)
        except ValueError as exc:
            raise ValueError(
                "Invalid REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS value: "
                f"{group_value}. Values must be non-negative integers."
            ) from exc
        if group_id < 0:
            raise ValueError(
                "Invalid REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS value: "
                f"{group_value}. Values must be non-negative integers."
            )
        parsed_groups.append(group_id)
    return parsed_groups


WORKSPACE_DISPLAY_FILE_LIMIT = int(
    os.getenv("WORKSPACE_DISPLAY_FILE_LIMIT", "100000"))
"""Maximum number of file entries returned by workspace listing endpoints."""

REANA_RUNTIME_FS_GROUP_CHANGE_POLICY = _parse_runtime_fs_group_change_policy(
    os.getenv("REANA_RUNTIME_FS_GROUP_CHANGE_POLICY")
)
"""Policy controlling runtime pod fsGroup ownership updates."""

REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS = (
    _parse_runtime_sessions_supplemental_groups(
        os.getenv("REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS")
    )
)
"""Supplemental groups applied to interactive-session pods."""

_VALID_GC_COMMANDS = {"ls", "list", "rm", "delete"}
"""Valid FORCE_GARBAGE_COLLECTION command values."""

_gc_env = os.getenv("FORCE_GARBAGE_COLLECTION", "")
FORCE_GARBAGE_COLLECTION = _parse_comma_separated_list(_gc_env)
"""Comma-separated list of commands that trigger a manual `gc.collect()` before operations.

Example:
  $ export FORCE_GARBAGE_COLLECTION=ls,list,rm,delete

Supported values:
- ls: trigger `gc.collect()` before listing workspace files
- list: trigger `gc.collect()` before listing all workflows
- rm: trigger `gc.collect()` before removing workspace files
- delete: trigger `gc.collect()` before deleting workflows
"""
_invalid_gc = sorted(set(FORCE_GARBAGE_COLLECTION) - _VALID_GC_COMMANDS)
if _invalid_gc:
    valid_gc_values = ", ".join(sorted(_VALID_GC_COMMANDS))
    invalid_gc_values = ", ".join(_invalid_gc)
    raise ValueError(
        "Invalid FORCE_GARBAGE_COLLECTION values: "
        f"{invalid_gc_values}. Valid values: {valid_gc_values}"
    )
