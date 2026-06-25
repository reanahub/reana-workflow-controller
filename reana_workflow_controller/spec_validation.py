# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Sandboxed REANA workflow specification loading and validation.

Loading a non-serial workflow specification means running the real engines
(Snakemake builds the DAG by executing the Snakefile, ``cwltool`` evaluates CWL,
yadage resolves the workflow), i.e. it executes *untrusted user code*. This
module runs that step inside a defense-in-depth Kubernetes Job:

* non-root, fixed UID/GID, no privilege escalation, all capabilities dropped,
  read-only root filesystem, ``RuntimeDefault`` seccomp profile;
* no service-account token, no user secrets, no workspace;
* the spec bundle mounted read-only (the writable scratch is an ephemeral
  ``emptyDir``, so the sandbox cannot write anywhere persistent);
* a ``NetworkPolicy`` that asks the cluster network plugin to block egress to
  cluster-internal addresses (other pods/services and link-local metadata);
  enforcement requires a NetworkPolicy-capable CNI, policies are additive, and
  standard Kubernetes NetworkPolicy does not block traffic to the pod's resident
  node;
  egress to the public internet is allowed by default (so remote CWL
  ``$import``/yadage ``toplevel`` references can be resolved) but an operator can
  request a policy with no egress allow rules -- see
  ``REANA_SPEC_VALIDATION_ALLOW_EGRESS``;
* a hard ``activeDeadlineSeconds`` and CPU/memory limits.

The only things read back from the sandbox are the container **exit code** and
its **stdout** (a sentinel-wrapped JSON report); the controller pulls both via
the Kubernetes API, so the sandbox needs no outbound capability of its own.
"""

import json
import logging
import posixpath
import time
import uuid

from kubernetes import client
from kubernetes.client.rest import ApiException

from reana_commons.config import (
    REANA_COMPONENT_PREFIX,
    REANA_RUNTIME_KUBERNETES_NAMESPACE,
    WORKFLOW_RUNTIME_USER_GID,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_commons.k8s.api_client import (
    current_k8s_batchv1_api_client,
    current_k8s_corev1_api_client,
    current_k8s_networking_api_client,
)
from reana_commons.k8s.volumes import REANA_SHARED_VOLUME_NAME, get_reana_shared_volume
from reana_commons.validation.sandbox import REPORT_END, REPORT_START

from reana_workflow_controller.config import (
    REANA_WORKFLOW_VALIDATOR_ENV_VARS,
    REANA_WORKFLOW_VALIDATOR_IMAGE,
    SPEC_VALIDATION_ALLOW_EGRESS,
    SPEC_VALIDATION_BLOCKED_EGRESS_CIDRS,
    SPEC_VALIDATION_CPU_LIMIT,
    SPEC_VALIDATION_DNS_NAMESERVERS,
    SPEC_VALIDATION_EPHEMERAL_STORAGE_LIMIT,
    SPEC_VALIDATION_EPHEMERAL_STORAGE_REQUEST,
    SPEC_VALIDATION_LOG_LIMIT_BYTES,
    SPEC_VALIDATION_LOG_TAIL_LINES,
    SPEC_VALIDATION_MAX_BYTES,
    SPEC_VALIDATION_MAX_FILES,
    SPEC_VALIDATION_MAX_TIMEOUT,
    SPEC_VALIDATION_MEMORY_LIMIT,
    SPEC_VALIDATION_POLL_INTERVAL,
    SPEC_VALIDATION_TIMEOUT,
)

CONTAINER_NAME = "spec-loader"
VALIDATOR_APP_LABEL = "reana-run-validation"
VALIDATOR_INSTANCE_LABEL = "app.kubernetes.io/instance"

# Retry budget for reading a just-terminated validator pod's log: a container
# that exits right after writing its report can do so before the node flushes
# the log. One immediate read plus this many exponential-backoff retries (the
# base delay doubling each time: 0.1s, 0.2s, 0.4s, ...).
_REPORT_READ_RETRIES = 5
_REPORT_READ_BASE_DELAY = 0.1

log = logging.getLogger(__name__)


def _validator_labels(component_prefix=None):
    """Return labels that identify one release's validator pods."""
    return {
        "reana_workflow_mode": "spec-validation",
        "app": VALIDATOR_APP_LABEL,
        VALIDATOR_INSTANCE_LABEL: component_prefix or REANA_COMPONENT_PREFIX,
    }


class SpecValidationError(Exception):
    """Raised on infrastructure failure of the sandboxed validation Job."""


def validate_spec_in_sandbox(bundle_path, timeout=None):
    """Load a spec bundle in the sandboxed loader Job and return its result.

    The sandbox is a pure loader: it loads the (untrusted) specification and
    emits the serialized result. It applies no cluster policy, so none is passed
    in here -- reana-server validates the returned specification itself.

    :param bundle_path: Path to the raw spec bundle *relative to the shared
        volume root*; mounted read-only into the sandbox at ``/validation/input``.
    :param timeout: Override for the Job ``activeDeadlineSeconds``.
    :returns: ``(exit_code, report)`` where ``report`` is the parsed JSON report
        (``{"reana_specification", "error"}``).
    :raises SpecValidationError: on infrastructure failure (Job could not be
        created/observed, timed out, or produced no parseable report).
    """
    bundle_path = _validate_bundle_path(bundle_path)
    # Clamp a caller-supplied override to a sane range: default when unset or
    # non-positive, and never exceed the configured maximum. This keeps the Job
    # ``activeDeadlineSeconds`` valid and bounds worker occupancy.
    if not timeout or timeout < 1:
        timeout = SPEC_VALIDATION_TIMEOUT
    else:
        timeout = min(timeout, SPEC_VALIDATION_MAX_TIMEOUT)
    job_name = "{prefix}-run-validation-{suffix}".format(
        prefix=REANA_COMPONENT_PREFIX, suffix=uuid.uuid4().hex[:8]
    )

    _ensure_egress_network_policy()
    job = _build_job(job_name, bundle_path, timeout)

    try:
        current_k8s_batchv1_api_client.create_namespaced_job(
            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE, body=job
        )
    except ApiException as e:
        raise SpecValidationError(
            "Could not create spec validation job: {}".format(e)
        ) from e

    try:
        exit_code, pod_name = _wait_for_job(job_name, timeout)
        report = _read_report(pod_name)
    finally:
        _delete_job(job_name)

    if report is None:
        raise SpecValidationError(
            "Spec validation job produced no parseable report (exit code "
            "{}).".format(exit_code)
        )
    return exit_code, report


def _build_job(job_name, bundle_path, timeout):
    """Build the hardened V1Job for a single spec loading run."""
    labels = _validator_labels()
    metadata = client.V1ObjectMeta(
        name=job_name,
        namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
        labels=labels,
    )

    # The bundle is a sub-path of the shared volume, mounted read-only. All
    # writable paths are ephemeral emptyDirs, so nothing the sandbox does can
    # touch persistent storage.
    shared_volume = get_reana_shared_volume()
    scratch_volume = client.V1Volume(
        name="spec-validation-scratch",
        empty_dir=client.V1EmptyDirVolumeSource(
            size_limit=SPEC_VALIDATION_EPHEMERAL_STORAGE_LIMIT
        ),
    )

    fixed_env = [
        client.V1EnvVar(name="REANA_VALIDATION_INPUT_DIR", value="/validation/input"),
        client.V1EnvVar(
            name="REANA_VALIDATION_WORK_DIR", value="/validation/scratch/work"
        ),
        client.V1EnvVar(name="HOME", value="/validation/scratch/work"),
        client.V1EnvVar(name="TMPDIR", value="/validation/scratch/tmp"),
        client.V1EnvVar(
            name="REANA_SPEC_BUNDLE_MAX_FILES",
            value=str(SPEC_VALIDATION_MAX_FILES),
        ),
        client.V1EnvVar(
            name="REANA_SPEC_BUNDLE_MAX_BYTES",
            value=str(SPEC_VALIDATION_MAX_BYTES),
        ),
    ]
    validator_env = [
        client.V1EnvVar(**env_var) for env_var in REANA_WORKFLOW_VALIDATOR_ENV_VARS
    ]

    container = client.V1Container(
        name=CONTAINER_NAME,
        image=REANA_WORKFLOW_VALIDATOR_IMAGE,
        image_pull_policy="IfNotPresent",
        env=fixed_env + validator_env,
        volume_mounts=[
            client.V1VolumeMount(
                name=REANA_SHARED_VOLUME_NAME,
                mount_path="/validation/input",
                sub_path=bundle_path,
                read_only=True,
            ),
            client.V1VolumeMount(
                name="spec-validation-scratch", mount_path="/validation/scratch"
            ),
        ],
        security_context=client.V1SecurityContext(
            run_as_user=int(WORKFLOW_RUNTIME_USER_UID),
            run_as_group=int(WORKFLOW_RUNTIME_USER_GID),
            run_as_non_root=True,
            privileged=False,
            allow_privilege_escalation=False,
            read_only_root_filesystem=True,
            capabilities=client.V1Capabilities(drop=["ALL"]),
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        ),
        resources=client.V1ResourceRequirements(
            requests={
                "cpu": "100m",
                "memory": "256Mi",
                "ephemeral-storage": SPEC_VALIDATION_EPHEMERAL_STORAGE_REQUEST,
            },
            limits={
                "cpu": SPEC_VALIDATION_CPU_LIMIT,
                "memory": SPEC_VALIDATION_MEMORY_LIMIT,
                "ephemeral-storage": SPEC_VALIDATION_EPHEMERAL_STORAGE_LIMIT,
            },
        ),
    )

    # When egress is allowed, pin the pod to public resolvers instead of
    # cluster DNS: kube-dns sits on a blocked cluster-internal address, so
    # without this the pod could not resolve any remote workflow reference. This
    # avoids intentionally allowing kube-dns while name resolution still works.
    # Actual isolation depends on the CNI and standard NetworkPolicy limitations.
    # When egress is disabled the default DNS config is harmless -- the policy
    # contains no egress allow rules.
    dns_kwargs = {}
    if SPEC_VALIDATION_ALLOW_EGRESS and SPEC_VALIDATION_DNS_NAMESERVERS:
        dns_kwargs = dict(
            dns_policy="None",
            dns_config=client.V1PodDNSConfig(
                nameservers=SPEC_VALIDATION_DNS_NAMESERVERS
            ),
        )

    pod_spec = client.V1PodSpec(
        containers=[container],
        restart_policy="Never",
        automount_service_account_token=False,
        enable_service_links=False,
        # The loader has nothing to flush or shut down gracefully, so kill it
        # immediately when the Job's ``activeDeadlineSeconds`` is exceeded --
        # otherwise the default 30s grace period is added on top of the deadline
        # before the pod (and hence the timeout) is observed.
        termination_grace_period_seconds=0,
        # Pod-level hardening complements the container security context above
        # (defense in depth) and sets ``fs_group`` so the non-root user owns the
        # writable ``emptyDir`` scratch volumes.
        security_context=client.V1PodSecurityContext(
            run_as_user=int(WORKFLOW_RUNTIME_USER_UID),
            run_as_group=int(WORKFLOW_RUNTIME_USER_GID),
            run_as_non_root=True,
            fs_group=int(WORKFLOW_RUNTIME_USER_GID),
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        ),
        volumes=[shared_volume, scratch_volume],
        **dns_kwargs,
    )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=metadata,
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels), spec=pod_spec
            ),
            backoff_limit=0,
            active_deadline_seconds=timeout,
            ttl_seconds_after_finished=300,
        ),
    )
    return job


def _validate_bundle_path(bundle_path):
    """Validate and normalize a path to mount (read-only) into the validator.

    The workflow-controller endpoint is internal, but callers must not be able
    to escape the shared volume. The path must be a normalized, *relative*
    sub-path of the shared volume with no ``..`` traversal. Only fresh,
    server-staged ``validation-tmp/<uuid>`` snapshots are legitimate;
    workspaces and repository checkouts must never be mounted.
    """
    if not bundle_path or bundle_path.startswith("/") or "\\" in bundle_path:
        raise SpecValidationError("Invalid spec validation bundle path.")

    normalized = posixpath.normpath(bundle_path)
    parts = normalized.split("/")
    if (
        normalized in (".", "..")
        or normalized != bundle_path
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise SpecValidationError("Invalid spec validation bundle path.")
    if len(parts) != 2 or parts[0] != "validation-tmp":
        raise SpecValidationError("Invalid spec validation bundle path.")
    try:
        parsed_uuid = uuid.UUID(parts[1])
    except (ValueError, AttributeError):
        raise SpecValidationError("Invalid spec validation bundle path.")
    if parsed_uuid.version != 4 or parsed_uuid.hex != parts[1]:
        raise SpecValidationError("Invalid spec validation bundle path.")
    return normalized


def _wait_for_job(job_name, timeout):
    """Poll the Job until its pod terminates; return ``(exit_code, pod_name)``.

    The pod is the source of truth for the container exit code and the report,
    so it is watched as primary. But a Job-level failure -- notably
    ``activeDeadlineSeconds`` being exceeded -- *deletes* the pod, which the pod
    watch can never observe; when the pod is gone we therefore consult the Job
    status so a timeout fails fast (and accurately) instead of waiting out the
    fallback deadline below.
    """
    # Allow for pod scheduling/startup on top of the in-container deadline.
    overall_timeout = timeout + 60
    deadline = time.time() + overall_timeout
    while time.time() < deadline:
        pod = _get_job_pod(job_name)
        if pod is not None:
            terminated = _terminated_container_state(pod)
            if terminated is not None:
                return terminated.exit_code, pod.metadata.name
            if pod.status and pod.status.phase == "Failed":
                # Failed without a terminated container state (e.g. evicted).
                return None, pod.metadata.name
        else:
            # No pod: it may have been deleted by a Job-level failure (the
            # deadline). A normal non-zero container exit keeps its pod, so this
            # only fires for the pod-deleted case and never pre-empts a real
            # load-error report.
            reason = _job_failure_reason(job_name)
            if reason is not None:
                raise SpecValidationError(
                    "Spec validation job {} failed: {}.".format(job_name, reason)
                )
        time.sleep(SPEC_VALIDATION_POLL_INTERVAL)
    raise SpecValidationError(
        "Spec validation job {} did not finish within {}s".format(
            job_name, overall_timeout
        )
    )


def _get_job_pod(job_name):
    """Return the (single) pod for a Job, or ``None`` if not created yet."""
    try:
        pods = current_k8s_corev1_api_client.list_namespaced_pod(
            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
            label_selector="job-name={}".format(job_name),
        )
    except ApiException as e:
        log.error("Could not list pods for job %s: %s", job_name, e)
        return None
    return pods.items[0] if pods.items else None


def _job_failure_reason(job_name):
    """Return the Job's failure reason if it has terminally failed, else ``None``.

    A Job-level failure -- most importantly ``activeDeadlineSeconds`` being
    exceeded -- deletes the running pod, which the pod watch in
    :func:`_wait_for_job` can never observe. Reading the Job status lets that
    watch fail fast (with an accurate reason, e.g. ``DeadlineExceeded``) once the
    pod is gone, instead of waiting out the fallback deadline.
    """
    try:
        job = current_k8s_batchv1_api_client.read_namespaced_job(
            name=job_name, namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE
        )
    except ApiException as e:
        log.error("Could not read spec validation job %s: %s", job_name, e)
        return None
    for condition in (job.status.conditions or []) if job.status else []:
        if condition.type == "Failed" and condition.status == "True":
            return condition.reason or "failed"
    return None


def _terminated_container_state(pod):
    """Return the validator container's terminated state, or ``None``."""
    for status in pod.status.container_statuses or []:
        if status.name == CONTAINER_NAME and status.state and status.state.terminated:
            return status.state.terminated
    return None


def _read_pod_logs(pod_name):
    r"""Read the tail of the validator container logs, best-effort.

    The validator may run untrusted code (Snakemake/CWL/Yadage loading) whose
    stdout/stderr would be merged into this single log stream. The validator
    suppresses loader output, but the controller still applies both a line tail
    and a byte cap so log retrieval remains bounded even if noisy output leaks.
    The trusted report is emitted last, so the sentinel-wrapped block lives in
    the tail; see :func:`_parse_report`, which extracts the *last* block.

    Uses ``_preload_content=False`` and decodes the raw bytes ourselves: with
    preloading, the Kubernetes client returns this plain-text endpoint as the
    ``str()`` of the raw bytes (``"b'...\\n...'"``), which mangles newlines and
    breaks report extraction.
    """
    try:
        response = current_k8s_corev1_api_client.read_namespaced_pod_log(
            name=pod_name,
            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
            container=CONTAINER_NAME,
            tail_lines=SPEC_VALIDATION_LOG_TAIL_LINES,
            limit_bytes=SPEC_VALIDATION_LOG_LIMIT_BYTES,
            _preload_content=False,
        )
        return response.data.decode("utf-8")
    except ApiException as e:
        log.error("Could not read logs for pod %s: %s", pod_name, e)
        return ""


def _parse_report(logs):
    """Extract the sentinel-wrapped JSON report from the pod logs.

    The genuine report is emitted last, *after* the untrusted loading step has
    run, so we take the **last** ``REPORT_START``/``REPORT_END`` block: untrusted
    code can print an earlier forged block to stdout, but it cannot emit anything
    after the real report. (This is only defense-in-depth -- the server re-runs
    the policy checks on the returned candidate spec and never trusts this
    verdict on its own.)
    """
    if not logs:
        return None
    start = logs.rfind(REPORT_START)
    if start == -1:
        return None
    end = logs.find(REPORT_END, start + len(REPORT_START))
    if end == -1:
        return None
    payload = logs[start + len(REPORT_START) : end].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        log.error("Could not parse validation report JSON: %s", e)
        return None


def _read_report(pod_name):
    """Read the pod logs and parse the report, retrying briefly on an empty read.

    A container that exits within a moment of writing its report can terminate
    before the node has flushed its log, so an immediate read comes back empty
    and yields no parseable report. This is most visible for specs that *fail to
    load* quickly (a valid spec loads slowly enough for the log to settle). Retry
    the read up to 5 times with exponential backoff (0.1s, 0.2s, 0.4s, 0.8s,
    1.6s); the genuine report is always at the tail, so a short wait closes the
    flush window. Returns the parsed report, or ``None`` if none appears (e.g. a
    killed/hung loader that never emitted one).
    """
    delay = _REPORT_READ_BASE_DELAY
    for attempt in range(_REPORT_READ_RETRIES + 1):  # one immediate read + retries
        report = _parse_report(_read_pod_logs(pod_name))
        if report is not None:
            return report
        if attempt < _REPORT_READ_RETRIES:
            time.sleep(delay)
            delay *= 2
    return None


def _delete_job(job_name):
    """Delete the validation Job and its pod, best-effort."""
    try:
        current_k8s_batchv1_api_client.delete_namespaced_job(
            name=job_name,
            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
            propagation_policy="Background",
        )
    except ApiException as e:
        if e.status != 404:
            log.error("Could not delete spec validation job %s: %s", job_name, e)


def _build_egress_rules():
    """Build the validator pod's egress allow-list.

    When egress is disabled the policy contains no egress allow rules. When it
    is enabled the public-internet range is allowed with configured internal
    ranges carved out via the ``ipBlock`` ``except`` list. DNS resolution still
    works because that rule permits all ports (including 53) to public
    addresses; the in-cluster DNS resolver is normally covered by the internal
    ranges. Actual enforcement depends on the cluster CNI, applicable policies
    combine additively, and standard NetworkPolicy does not filter traffic to
    the pod's resident node.
    """
    if not SPEC_VALIDATION_ALLOW_EGRESS:
        return []  # empty egress rule list => deny all egress

    public_internet = client.V1NetworkPolicyPeer(
        ip_block=client.V1IPBlock(
            cidr="0.0.0.0/0",
            _except=SPEC_VALIDATION_BLOCKED_EGRESS_CIDRS or None,
        )
    )
    rules = [
        client.V1NetworkPolicyEgressRule(
            to=[public_internet],
        ),
    ]
    return rules


def _build_network_policy(component_prefix=None):
    """Build the egress policy scoped to one REANA release instance."""
    component_prefix = component_prefix or REANA_COMPONENT_PREFIX
    selector_labels = _validator_labels(component_prefix)
    return client.V1NetworkPolicy(
        api_version="networking.k8s.io/v1",
        kind="NetworkPolicy",
        metadata=client.V1ObjectMeta(
            name="{}-run-validation-egress".format(component_prefix),
            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(match_labels=selector_labels),
            policy_types=["Egress", "Ingress"],
            egress=_build_egress_rules(),
            ingress=[],  # empty ingress rule list => deny all ingress
        ),
    )


def _ensure_egress_network_policy():
    """Reconcile this release's validator NetworkPolicy before a sandbox.

    The policy requests denial of all *ingress* and egress to configured
    cluster-internal ranges; whether public egress is allowed is governed by
    ``REANA_SPEC_VALIDATION_ALLOW_EGRESS`` (see :func:`_build_egress_rules`). It
    is reconciled on every run so that flipping the configuration takes effect,
    and any API failure raises rather than deliberately running without the
    policy object. This is a fail-closed *ordering gate*, not proof of traffic
    isolation: enforcement requires a NetworkPolicy-capable CNI, policies are
    additive, and resident-node traffic is outside standard NetworkPolicy's
    guarantees.

    :raises SpecValidationError: if the policy cannot be created or updated.
    """
    for _attempt in range(3):
        policy = _build_network_policy()
        try:
            current_k8s_networking_api_client.create_namespaced_network_policy(
                namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE, body=policy
            )
            return
        except ApiException as error:
            if error.status != 409:
                raise SpecValidationError(
                    "Could not apply the spec validator network policy: {}".format(
                        error
                    )
                ) from error

            try:
                existing_policy = (
                    current_k8s_networking_api_client.read_namespaced_network_policy(
                        name=policy.metadata.name,
                        namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                    )
                )
            except ApiException as read_error:
                if read_error.status == 404:
                    continue
                raise SpecValidationError(
                    "Could not read the spec validator network policy: {}".format(
                        read_error
                    )
                ) from read_error

            if existing_policy.spec.to_dict() == policy.spec.to_dict():
                return

            policy.metadata.resource_version = existing_policy.metadata.resource_version
            try:
                current_k8s_networking_api_client.replace_namespaced_network_policy(
                    name=policy.metadata.name,
                    namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                    body=policy,
                )
                return
            except ApiException as replace_error:
                if replace_error.status in (404, 409):
                    continue
                raise SpecValidationError(
                    "Could not update the spec validator network policy: {}".format(
                        replace_error
                    )
                ) from replace_error

    raise SpecValidationError(
        "Could not reconcile the spec validator network policy after 3 attempts."
    )
