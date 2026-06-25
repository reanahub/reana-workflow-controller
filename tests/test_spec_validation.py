# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for the sandboxed specification validation job manager."""

import json

import pytest
from kubernetes.client.rest import ApiException
from mock import DEFAULT, Mock, patch

from reana_workflow_controller import spec_validation
from reana_workflow_controller.spec_validation import (
    REPORT_END,
    REPORT_START,
    SpecValidationError,
    _build_egress_rules,
    _build_job,
    _build_network_policy,
    _ensure_egress_network_policy,
    _job_failure_reason,
    _parse_report,
    _read_pod_logs,
    _read_report,
    _validate_bundle_path,
    _validator_labels,
    _wait_for_job,
)

VALID_BUNDLE_PATH = "validation-tmp/123e4567e89b42d3a456426614174000"


def _wrap_report(report):
    """Wrap a report dict the way the validator prints it to stdout."""
    return "some log line\n{}\n{}\n{}\nmore logs\n".format(
        REPORT_START, json.dumps(report), REPORT_END
    )


def test_parse_report_extracts_sentinel_wrapped_json():
    """A sentinel-wrapped report is parsed out of noisy logs."""
    report = {"valid": True, "errors": [], "warnings": []}
    assert _parse_report(_wrap_report(report)) == report


@pytest.mark.parametrize("logs", ["", "no sentinels here", None])
def test_parse_report_returns_none_without_sentinels(logs):
    """Logs without a valid report yield ``None``."""
    assert _parse_report(logs) is None


def test_parse_report_returns_none_on_bad_json():
    """A corrupt JSON payload does not raise."""
    logs = "{}\nnot-json\n{}".format(REPORT_START, REPORT_END)
    assert _parse_report(logs) is None


def test_parse_report_single_line_report_amid_interleaved_noise():
    """A single-line report is parsed even with stderr-like lines around it.

    The validator emits the report on one line precisely so that interleaved
    stderr output (which Kubernetes merges line-by-line) lands before or after
    it, never inside it.
    """
    report = {"reana_specification": {"workflow": {"type": "serial"}}, "error": None}
    logs = "traceback frame 1\n{}{}{}\ntraceback frame 2\n".format(
        REPORT_START, json.dumps(report), REPORT_END
    )
    assert _parse_report(logs) == report


def test_parse_report_prefers_last_block_over_forged_earlier_one():
    """The genuine (last) report wins over an earlier block forged by the spec.

    Untrusted loading code can print its own sentinel block to stdout, but it
    cannot emit anything after the real report, so the last block is taken.
    """
    forged = {"reana_specification": "forged"}
    genuine = {"reana_specification": {"workflow": {"type": "serial"}}, "error": None}
    logs = "{s}\n{f}\n{e}\nloading the workflow...\n{s}\n{g}\n{e}\n".format(
        s=REPORT_START,
        e=REPORT_END,
        f=json.dumps(forged),
        g=json.dumps(genuine),
    )
    assert _parse_report(logs) == genuine


def test_build_egress_rules_denies_all_when_disabled(monkeypatch):
    """Disabled egress produces no allow rules in the policy manifest."""
    monkeypatch.setattr(spec_validation, "SPEC_VALIDATION_ALLOW_EGRESS", False)
    assert _build_egress_rules() == []


def test_build_egress_rules_excludes_internal_when_enabled(monkeypatch):
    """The public-egress rule carves out the configured internal CIDRs."""
    monkeypatch.setattr(spec_validation, "SPEC_VALIDATION_ALLOW_EGRESS", True)
    monkeypatch.setattr(
        spec_validation, "SPEC_VALIDATION_BLOCKED_EGRESS_CIDRS", ["10.0.0.0/8"]
    )
    rules = _build_egress_rules()
    # A single public-egress rule with the internal range carved out.
    assert len(rules) == 1
    ip_block = rules[0].to[0].ip_block
    assert ip_block.cidr == "0.0.0.0/0"
    assert "10.0.0.0/8" in ip_block._except
    # No port restriction: all ports (including DNS/53) are permitted to public
    # addresses, while internal ranges (incl. the resolver) stay blocked via the
    # ``except`` list -- so no separate DNS rule is needed.
    assert not rules[0].ports


@pytest.mark.parametrize(
    "bundle_path",
    [
        VALID_BUNDLE_PATH,
    ],
)
def test_validate_bundle_path_accepts_safe_subpaths(bundle_path):
    """Normalized relative sub-paths of the shared volume are accepted."""
    assert _validate_bundle_path(bundle_path) == bundle_path


@pytest.mark.parametrize(
    "bundle_path",
    [
        "",
        ".",
        "/validation-tmp/abcd",
        "../escape",
        "validation-tmp/../workspace",
        "validation-tmp//abcd",
        "validation-tmp\\abcd",
        "validation-tmp/abcd",
        "validation-tmp",
        "users/00000000-0000-0000-0000-000000000000/workflows/abcd",
    ],
)
def test_validate_bundle_path_rejects_unsafe_paths(bundle_path):
    """The validator cannot be pointed outside the shared volume (traversal)."""
    with pytest.raises(SpecValidationError):
        _validate_bundle_path(bundle_path)


def test_build_job_is_hardened():
    """The validator Job drops privileges, mounts no SA token, and is bounded."""
    job = _build_job("job-1", VALID_BUNDLE_PATH, timeout=15)
    pod_spec = job.spec.template.spec
    container = pod_spec.containers[0]

    sec = container.security_context
    assert sec.run_as_non_root is True
    assert sec.read_only_root_filesystem is True
    assert sec.allow_privilege_escalation is False
    assert sec.capabilities.drop == ["ALL"]

    # UID/GID must be ints: the runtime user env values arrive as strings, and a
    # string here makes the Kubernetes API reject the Job ("cannot unmarshal
    # string into ...runAsGroup...int64"), so the whole securityContext must be
    # numeric.
    pod_sec = pod_spec.security_context
    for value in (
        sec.run_as_user,
        sec.run_as_group,
        pod_sec.run_as_user,
        pod_sec.run_as_group,
        pod_sec.fs_group,
    ):
        assert isinstance(value, int)

    assert pod_spec.automount_service_account_token is False
    assert job.spec.backoff_limit == 0
    assert job.spec.active_deadline_seconds == 15

    # The bundle is mounted read-only.
    bundle_mount = next(
        m for m in container.volume_mounts if m.mount_path == "/validation/input"
    )
    assert bundle_mount.read_only is True
    assert bundle_mount.sub_path == VALID_BUNDLE_PATH
    scratch_volume = next(
        volume
        for volume in pod_spec.volumes
        if getattr(volume, "name", None) == "spec-validation-scratch"
    )
    assert (
        scratch_volume.empty_dir.size_limit
        == spec_validation.SPEC_VALIDATION_EPHEMERAL_STORAGE_LIMIT
    )
    assert (
        container.resources.limits["ephemeral-storage"]
        == spec_validation.SPEC_VALIDATION_EPHEMERAL_STORAGE_LIMIT
    )

    # The sandbox is a pure loader: no cluster policy is injected into it.
    assert not any(e.name == "REANA_VALIDATION_POLICY" for e in container.env)

    # A hung loader is killed immediately when the deadline is exceeded (no grace
    # period added on top of activeDeadlineSeconds).
    assert pod_spec.termination_grace_period_seconds == 0


def test_build_job_adds_configured_validator_environment(monkeypatch):
    """Operator validator environment is added after the fixed loader contract."""
    monkeypatch.setattr(
        spec_validation,
        "REANA_WORKFLOW_VALIDATOR_ENV_VARS",
        [{"name": "REANA_LOG_LEVEL", "value": "DEBUG"}],
    )
    container = _build_job(
        "job-1", VALID_BUNDLE_PATH, timeout=15
    ).spec.template.spec.containers[0]

    assert {env.name: env.value for env in container.env} == {
        "REANA_VALIDATION_INPUT_DIR": "/validation/input",
        "REANA_VALIDATION_WORK_DIR": "/validation/scratch/work",
        "HOME": "/validation/scratch/work",
        "TMPDIR": "/validation/scratch/tmp",
        "REANA_SPEC_BUNDLE_MAX_FILES": str(spec_validation.SPEC_VALIDATION_MAX_FILES),
        "REANA_SPEC_BUNDLE_MAX_BYTES": str(spec_validation.SPEC_VALIDATION_MAX_BYTES),
        "REANA_LOG_LEVEL": "DEBUG",
    }


def test_network_policy_selects_only_its_release_validator_pods():
    """Two releases in one namespace do not share validator egress policy."""
    first_labels = _validator_labels("reana-first")
    second_labels = _validator_labels("reana-second")
    first_policy = _build_network_policy("reana-first")
    first_selector = first_policy.spec.pod_selector.match_labels
    second_selector = _build_network_policy(
        "reana-second"
    ).spec.pod_selector.match_labels

    def selects(selector, labels):
        return all(labels.get(key) == value for key, value in selector.items())

    assert selects(first_selector, first_labels)
    assert not selects(first_selector, second_labels)
    assert selects(second_selector, second_labels)
    assert not selects(second_selector, first_labels)
    assert first_labels["app"] == "reana-run-validation"
    assert first_policy.metadata.name == "reana-first-run-validation-egress"


def test_read_report_retries_until_log_is_flushed(monkeypatch):
    """An initially-empty (not-yet-flushed) log is retried until the report appears.

    A fast-failing loader can terminate before the node flushes its log; the read
    must retry rather than mislabel the empty read as a missing report.
    """
    report = {"reana_specification": {"workflow": {"type": "serial"}}, "error": None}
    reads = iter(["", "", _wrap_report(report)])  # empty twice, then the report
    monkeypatch.setattr(spec_validation, "_read_pod_logs", lambda name: next(reads))
    monkeypatch.setattr(spec_validation.time, "sleep", lambda s: None)
    assert _read_report("pod-1") == report


def test_read_report_gives_up_when_no_report_ever(monkeypatch):
    """A pod that never emits a report (e.g. killed) yields None after retries."""
    monkeypatch.setattr(spec_validation, "_read_pod_logs", lambda name: "")
    monkeypatch.setattr(spec_validation.time, "sleep", lambda s: None)
    assert _read_report("pod-1") is None


def test_read_pod_logs_is_byte_bounded(monkeypatch):
    """Kubernetes log retrieval is capped by bytes, not only by line count."""
    response = Mock(data=b"")
    client = Mock()
    client.read_namespaced_pod_log = Mock(return_value=response)
    monkeypatch.setattr(spec_validation, "current_k8s_corev1_api_client", client)
    monkeypatch.setattr(spec_validation, "SPEC_VALIDATION_LOG_TAIL_LINES", 500)
    monkeypatch.setattr(spec_validation, "SPEC_VALIDATION_LOG_LIMIT_BYTES", 1024)

    assert _read_pod_logs("pod-1") == ""
    client.read_namespaced_pod_log.assert_called_once()
    assert client.read_namespaced_pod_log.call_args.kwargs["tail_lines"] == 500
    assert client.read_namespaced_pod_log.call_args.kwargs["limit_bytes"] == 1024


def test_read_pod_logs_returns_report_from_bounded_tail(monkeypatch):
    """The report is retained by the bounded (tail) read even when earlier output is dropped.

    The byte/line cap is applied from the *end* of the log, so a report emitted
    last survives it; the decoded tail then parses cleanly. This is the benign
    counterpart of the DoS bound: capping does not lose the genuine report.
    """
    report = {"reana_specification": {"workflow": {"type": "serial"}}, "error": None}
    tail = "...older output dropped by the cap...\n" + _wrap_report(report)
    response = Mock(data=tail.encode("utf-8"))
    client = Mock()
    client.read_namespaced_pod_log = Mock(return_value=response)
    monkeypatch.setattr(spec_validation, "current_k8s_corev1_api_client", client)

    assert _parse_report(_read_pod_logs("pod-1")) == report


def test_validate_spec_in_sandbox_raises_infra_error_when_no_report(monkeypatch):
    """No parseable report within the cap is an infrastructure failure, not a verdict.

    A flooded or truncated log whose report cannot be recovered under the byte
    cap must surface as a ``SpecValidationError`` (the internal / HTTP 500 path),
    never as a valid-or-invalid result (SNDBX-08).
    """
    monkeypatch.setattr(spec_validation, "_ensure_egress_network_policy", lambda: None)
    monkeypatch.setattr(spec_validation, "_build_job", lambda *a, **k: Mock())
    monkeypatch.setattr(spec_validation, "current_k8s_batchv1_api_client", Mock())
    monkeypatch.setattr(
        spec_validation, "_wait_for_job", lambda name, timeout: (0, "pod-1")
    )
    monkeypatch.setattr(spec_validation, "_read_report", lambda name: None)
    monkeypatch.setattr(spec_validation, "_delete_job", lambda name: None)

    with pytest.raises(SpecValidationError, match="no parseable report"):
        spec_validation.validate_spec_in_sandbox(VALID_BUNDLE_PATH)


def test_validate_spec_in_sandbox_clamps_timeout(monkeypatch):
    """A caller-supplied timeout is clamped to a sane range before Job creation.

    Non-positive values (which Kubernetes rejects as ``activeDeadlineSeconds``)
    fall back to the default, and an over-large value is capped at the
    configured maximum so a caller cannot request an arbitrarily long-lived Job
    (SSV-07).
    """
    from reana_workflow_controller.config import (
        SPEC_VALIDATION_MAX_TIMEOUT,
        SPEC_VALIDATION_TIMEOUT,
    )

    captured = {}

    def fake_build_job(job_name, bundle_path, timeout):
        captured["job_name"] = job_name
        captured["timeout"] = timeout
        return Mock()

    monkeypatch.setattr(spec_validation, "_ensure_egress_network_policy", lambda: None)
    monkeypatch.setattr(spec_validation, "_build_job", fake_build_job)
    monkeypatch.setattr(spec_validation, "current_k8s_batchv1_api_client", Mock())
    monkeypatch.setattr(
        spec_validation, "_wait_for_job", lambda name, timeout: (0, "pod-1")
    )
    monkeypatch.setattr(
        spec_validation, "_read_report", lambda name: {"reana_specification": {}}
    )
    monkeypatch.setattr(spec_validation, "_delete_job", lambda name: None)

    for supplied, expected in [
        (None, SPEC_VALIDATION_TIMEOUT),
        (0, SPEC_VALIDATION_TIMEOUT),
        (-1, SPEC_VALIDATION_TIMEOUT),
        (SPEC_VALIDATION_MAX_TIMEOUT + 10000, SPEC_VALIDATION_MAX_TIMEOUT),
        (5, 5),
    ]:
        spec_validation.validate_spec_in_sandbox(VALID_BUNDLE_PATH, timeout=supplied)
        assert captured["timeout"] == expected
        assert captured["job_name"].startswith("reana-run-validation-")


def test_job_failure_reason_detects_deadline(monkeypatch):
    """The Job's DeadlineExceeded failure condition is surfaced."""
    cond = Mock()
    cond.type, cond.status, cond.reason = "Failed", "True", "DeadlineExceeded"
    job = Mock()
    job.status = Mock(conditions=[cond])
    client = Mock()
    client.read_namespaced_job = Mock(return_value=job)
    monkeypatch.setattr(spec_validation, "current_k8s_batchv1_api_client", client)
    assert _job_failure_reason("job-1") == "DeadlineExceeded"


def test_job_failure_reason_none_while_running(monkeypatch):
    """A Job with no failure condition returns None."""
    job = Mock()
    job.status = Mock(conditions=[])
    client = Mock()
    client.read_namespaced_job = Mock(return_value=job)
    monkeypatch.setattr(spec_validation, "current_k8s_batchv1_api_client", client)
    assert _job_failure_reason("job-1") is None


def test_wait_for_job_fails_fast_when_deadline_deletes_pod(monkeypatch):
    """A deadline that deletes the pod is detected via the Job status, not waited out."""
    monkeypatch.setattr(spec_validation, "_get_job_pod", lambda name: None)
    monkeypatch.setattr(
        spec_validation, "_job_failure_reason", lambda name: "DeadlineExceeded"
    )
    monkeypatch.setattr(spec_validation.time, "sleep", lambda s: None)
    with pytest.raises(SpecValidationError, match="DeadlineExceeded"):
        _wait_for_job("job-1", timeout=1)


def test_build_job_pins_public_dns_when_egress_allowed(monkeypatch):
    """With egress allowed the pod resolves via public DNS, not cluster DNS."""
    monkeypatch.setattr(spec_validation, "SPEC_VALIDATION_ALLOW_EGRESS", True)
    monkeypatch.setattr(
        spec_validation, "SPEC_VALIDATION_DNS_NAMESERVERS", ["1.1.1.1", "8.8.8.8"]
    )
    pod_spec = _build_job("job-1", VALID_BUNDLE_PATH, timeout=15).spec.template.spec
    assert pod_spec.dns_policy == "None"
    assert pod_spec.dns_config.nameservers == ["1.1.1.1", "8.8.8.8"]


def test_build_job_keeps_default_dns_when_egress_disabled(monkeypatch):
    """With egress disabled no custom DNS resolver is configured."""
    monkeypatch.setattr(spec_validation, "SPEC_VALIDATION_ALLOW_EGRESS", False)
    pod_spec = _build_job("job-1", VALID_BUNDLE_PATH, timeout=15).spec.template.spec
    assert pod_spec.dns_policy is None
    assert pod_spec.dns_config is None


def test_ensure_network_policy_creates_when_absent():
    """A fresh policy is created."""
    with patch.multiple(
        "reana_workflow_controller.spec_validation",
        current_k8s_networking_api_client=DEFAULT,
    ) as mocks:
        _ensure_egress_network_policy()
        mocks[
            "current_k8s_networking_api_client"
        ].create_namespaced_network_policy.assert_called_once()


def test_ensure_network_policy_replaces_on_conflict():
    """An existing policy is read and replaced with its resourceVersion."""
    client = Mock()
    client.create_namespaced_network_policy = Mock(side_effect=ApiException(status=409))
    existing_policy = _build_network_policy()
    existing_policy.spec.ingress = None
    existing_policy.metadata.resource_version = "12345"
    client.read_namespaced_network_policy = Mock(return_value=existing_policy)
    with patch.object(spec_validation, "current_k8s_networking_api_client", client):
        _ensure_egress_network_policy()
        client.read_namespaced_network_policy.assert_called_once()
        replace_call = client.replace_namespaced_network_policy.call_args
        assert replace_call.kwargs["body"].metadata.resource_version == "12345"


def test_ensure_network_policy_keeps_equivalent_existing_policy():
    """Steady-state validation does not issue unnecessary replacements."""
    client = Mock()
    client.create_namespaced_network_policy = Mock(side_effect=ApiException(status=409))
    existing_policy = _build_network_policy()
    existing_policy.metadata.resource_version = "12345"
    client.read_namespaced_network_policy = Mock(return_value=existing_policy)
    with patch.object(spec_validation, "current_k8s_networking_api_client", client):
        _ensure_egress_network_policy()

    client.replace_namespaced_network_policy.assert_not_called()


def test_ensure_network_policy_retries_create_after_read_not_found():
    """Deletion between create and read restarts reconciliation."""
    client = Mock()
    client.create_namespaced_network_policy = Mock(
        side_effect=[ApiException(status=409), None]
    )
    client.read_namespaced_network_policy = Mock(side_effect=ApiException(status=404))
    with patch.object(spec_validation, "current_k8s_networking_api_client", client):
        _ensure_egress_network_policy()

    assert client.create_namespaced_network_policy.call_count == 2


def test_ensure_network_policy_refreshes_after_stale_replace():
    """A stale resourceVersion conflict retries with the newest policy."""
    client = Mock()
    client.create_namespaced_network_policy = Mock(
        side_effect=[ApiException(status=409), ApiException(status=409)]
    )
    stale = _build_network_policy()
    stale.spec.ingress = None
    stale.metadata.resource_version = "old"
    current = _build_network_policy()
    current.metadata.resource_version = "new"
    client.read_namespaced_network_policy = Mock(side_effect=[stale, current])
    client.replace_namespaced_network_policy = Mock(
        side_effect=ApiException(status=409)
    )
    with patch.object(spec_validation, "current_k8s_networking_api_client", client):
        _ensure_egress_network_policy()

    assert client.create_namespaced_network_policy.call_count == 2
    client.replace_namespaced_network_policy.assert_called_once()


def test_ensure_network_policy_bounds_conflict_retries():
    """Persistent create/read races fail closed after the bounded retry count."""
    client = Mock()
    client.create_namespaced_network_policy = Mock(side_effect=ApiException(status=409))
    client.read_namespaced_network_policy = Mock(side_effect=ApiException(status=404))
    with patch.object(spec_validation, "current_k8s_networking_api_client", client):
        with pytest.raises(SpecValidationError, match="after 3 attempts"):
            _ensure_egress_network_policy()

    assert client.create_namespaced_network_policy.call_count == 3


def test_ensure_network_policy_fails_closed_when_existing_policy_cannot_be_read():
    """A failed read never falls through to a stale or unconditional replace."""
    client = Mock()
    client.create_namespaced_network_policy = Mock(side_effect=ApiException(status=409))
    client.read_namespaced_network_policy = Mock(side_effect=ApiException(status=403))
    with patch.object(spec_validation, "current_k8s_networking_api_client", client):
        with pytest.raises(SpecValidationError):
            _ensure_egress_network_policy()
        client.replace_namespaced_network_policy.assert_not_called()


def test_ensure_network_policy_fails_closed():
    """Any other API error is fatal (the sandbox must not run unprotected)."""
    client = Mock()
    client.create_namespaced_network_policy = Mock(side_effect=ApiException(status=403))
    with patch.object(spec_validation, "current_k8s_networking_api_client", client):
        with pytest.raises(SpecValidationError):
            _ensure_egress_network_policy()
