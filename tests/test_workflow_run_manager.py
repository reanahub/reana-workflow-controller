# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2024, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Workflow-Controller WorkflowRunManager tests."""

from __future__ import absolute_import, print_function

import pytest
from kubernetes.client.rest import ApiException
from mock import DEFAULT, Mock, patch

from reana_commons.config import (
    KRB5_INIT_CONTAINER_NAME,
    KRB5_RENEW_CONTAINER_NAME,
    WORKFLOW_RUNTIME_USER_GID,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_db.database import Session
from reana_db.models import (
    RunStatus,
    InteractiveSession,
    InteractiveSessionType,
)

from reana_workflow_controller.config import (
    REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS,
    REANA_RUNTIME_FS_GROUP_CHANGE_POLICY,
)
from reana_workflow_controller.errors import REANAInteractiveSessionError
from reana_workflow_controller.workflow_run_manager import (
    KubernetesWorkflowRunManager,
    _container_image_aliases,
)


@pytest.fixture(autouse=True)
def interactive_session_environments_autouse(interactive_session_environments):
    pass


def test_start_interactive_session(sample_serial_workflow_in_db):
    """Test interactive workflow run deployment."""
    with patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_corev1_api_client=DEFAULT,
        current_k8s_networking_api_client=DEFAULT,
        current_k8s_appsv1_api_client=DEFAULT,
    ) as mocks:
        kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
        if len(InteractiveSessionType):
            kwrm.start_interactive_session(
                InteractiveSessionType(0).name, expose_secrets=False
            )
        mocks[
            "current_k8s_appsv1_api_client"
        ].create_namespaced_deployment.assert_called_once()
        mocks[
            "current_k8s_corev1_api_client"
        ].create_namespaced_service.assert_called_once()
        mocks[
            "current_k8s_networking_api_client"
        ].create_namespaced_ingress.assert_called_once()


def test_start_interactive_workflow_k8s_failure(sample_serial_workflow_in_db):
    """Test failure of an interactive workflow run deployment because of ."""
    mocked_k8s_client = Mock()
    mocked_k8s_client.create_namespaced_deployment = Mock(
        side_effect=ApiException(reason="some reason")
    )
    with patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_appsv1_api_client=mocked_k8s_client,
        current_k8s_corev1_api_client=DEFAULT,
        current_k8s_networking_api_client=DEFAULT,
    ):
        with pytest.raises(
            REANAInteractiveSessionError, match=r".*Kubernetes has failed.*"
        ):
            kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
            if len(InteractiveSessionType):
                kwrm.start_interactive_session(
                    InteractiveSessionType(0).name, expose_secrets=False
                )


def test_atomic_creation_of_interactive_session(sample_serial_workflow_in_db):
    """Test atomic creation of interactive sessions.

    All interactive session should be created as well as writing the state
    to DB, either all should be done or nothing.
    """
    mocked_k8s_client = Mock()
    mocked_k8s_client.create_namespaced_deployment = Mock(
        side_effect=ApiException(reason="Error while creating deployment")
    )
    # Raise 404 when deleting Deployment, because it doesn't exist
    mocked_k8s_client.delete_namespaced_deployment = Mock(
        side_effect=ApiException(reason="Not Found")
    )
    with patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_appsv1_api_client=mocked_k8s_client,
        current_k8s_networking_api_client=DEFAULT,
        current_k8s_corev1_api_client=DEFAULT,
    ) as mocks:
        try:
            kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
            if len(InteractiveSessionType):
                kwrm.start_interactive_session(
                    InteractiveSessionType(0).name, expose_secrets=False
                )
        except REANAInteractiveSessionError:
            mocks[
                "current_k8s_corev1_api_client"
            ].delete_namespaced_service.assert_called_once()
            mocks[
                "current_k8s_networking_api_client"
            ].delete_namespaced_ingress.assert_called_once()
            mocked_k8s_client.delete_namespaced_deployment.assert_called_once()
            assert not sample_serial_workflow_in_db.sessions


def test_stop_workflow_backend_only_kubernetes(
    sample_serial_workflow_in_db, add_kubernetes_jobs_to_workflow
):
    """Test deletion of workflows with only Kubernetes based jobs."""
    workflow = sample_serial_workflow_in_db
    workflow.status = RunStatus.running
    with patch(
        "reana_workflow_controller.workflow_run_manager."
        "current_k8s_batchv1_api_client"
    ) as api_client:
        kwrm = KubernetesWorkflowRunManager(workflow)
        kwrm.stop_batch_workflow_run()
        # jobs are deleted by reana-job-controller, so this should be called
        # only once to delete the run-batch pod
        api_client.delete_namespaced_job.assert_called_once()
        assert (
            api_client.delete_namespaced_job.call_args.args[0]
            == f"reana-run-batch-{workflow.id_}"
        )


def test_interactive_session_closure(sample_serial_workflow_in_db, session):
    """Test closure of an interactive sessions."""
    mocked_k8s_client = Mock()
    workflow = sample_serial_workflow_in_db
    with patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_appsv1_api_client=mocked_k8s_client,
        current_k8s_networking_api_client=DEFAULT,
        current_k8s_corev1_api_client=DEFAULT,
    ):
        kwrm = KubernetesWorkflowRunManager(workflow)
        if len(InteractiveSessionType):
            kwrm.start_interactive_session(
                InteractiveSessionType(0).name, expose_secrets=False
            )

            int_session = (
                Session.query(InteractiveSession)
                .filter_by(
                    owner_id=workflow.owner_id,
                    type_=InteractiveSessionType(0).name,
                )
                .first()
            )
            assert int_session.status == RunStatus.created
            kwrm.stop_interactive_session(int_session.id_)
            assert not workflow.sessions


def test_container_image_aliases():
    """Test generation of docker image aliases."""
    image = "foo/bar"
    aliases = _container_image_aliases(image)
    assert "docker.io/foo/bar" in aliases
    assert "foo/bar" in aliases

    image = "docker.io/library/ubuntu:24.04"
    aliases = _container_image_aliases(image)
    assert "ubuntu:24.04" in aliases
    assert "library/ubuntu:24.04" in aliases
    assert "docker.io/library/ubuntu:24.04" in aliases

    image = "library/ubuntu:24.04"
    aliases = _container_image_aliases(image)
    assert "ubuntu:24.04" in aliases
    assert "library/ubuntu:24.04" in aliases
    assert "docker.io/library/ubuntu:24.04" in aliases


def test_interactive_session_not_allowed_image(sample_serial_workflow_in_db):
    """Test interactive workflow run deployment with not allowed image."""
    with patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_appsv1_api_client=DEFAULT,
        current_k8s_corev1_api_client=DEFAULT,
        current_k8s_networking_api_client=DEFAULT,
    ):
        with pytest.raises(
            REANAInteractiveSessionError,
            match=r".*this_image_is_not_allowed.*not allow.*",
        ):
            kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
            if len(InteractiveSessionType):
                kwrm.start_interactive_session(
                    InteractiveSessionType(0).name, image="this_image_is_not_allowed"
                )


def test_interactive_session_custom_image(sample_serial_workflow_in_db, monkeypatch):
    """Test interactive workflow run deployment with custom image."""
    monkeypatch.setitem(
        REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS["jupyter"], "allow_custom", True
    )
    with patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_appsv1_api_client=DEFAULT,
        current_k8s_corev1_api_client=DEFAULT,
        current_k8s_networking_api_client=DEFAULT,
    ) as mocks:
        kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
        if len(InteractiveSessionType):
            kwrm.start_interactive_session(
                InteractiveSessionType(0).name,
                image="this is my custom image",
                expose_secrets=False,
            )
        mocks[
            "current_k8s_appsv1_api_client"
        ].create_namespaced_deployment.assert_called_once()
        mocks[
            "current_k8s_corev1_api_client"
        ].create_namespaced_service.assert_called_once()
        mocks[
            "current_k8s_networking_api_client"
        ].create_namespaced_ingress.assert_called_once()


def test_create_job_spec_kerberos(
    sample_serial_workflow_in_db,
    kerberos_user_secrets,
    corev1_api_client_with_user_secrets,
):
    """Test creation of k8s job specification when Kerberos is required."""
    workflow = sample_serial_workflow_in_db
    workflow.reana_specification["workflow"].setdefault("resources", {})[
        "kerberos"
    ] = True

    with patch(
        "reana_commons.k8s.secrets.current_k8s_corev1_api_client",
        corev1_api_client_with_user_secrets(kerberos_user_secrets),
    ):
        kwrm = KubernetesWorkflowRunManager(workflow)
        job = kwrm._create_job_spec("run-batch-test")

    init_containers = job.spec.template.spec.init_containers
    assert len(init_containers) == 1
    assert init_containers[0]["name"] == KRB5_INIT_CONTAINER_NAME
    assert init_containers[0]["securityContext"] == {
        "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
        "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }

    renew_container = job.spec.template.spec.containers[-1]
    assert renew_container["name"] == KRB5_RENEW_CONTAINER_NAME
    assert renew_container["securityContext"] == {
        "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
        "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }

    volumes = [volume["name"] for volume in job.spec.template.spec.volumes]
    assert len(set(volumes)) == len(volumes)  # volumes have unique names
    assert any(volume.startswith("reana-secretsstore") for volume in volumes)
    assert "krb5-cache" in volumes
    assert "krb5-conf" in volumes


def test_create_job_spec_job_controller_runs_as_runtime_user(
    sample_serial_workflow_in_db,
    mock_user_secrets,
):
    """Test that run-batch containers run as the default non-root REANA user."""
    kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
    job = kwrm._create_job_spec("run-batch-test")

    workflow_engine, job_controller = job.spec.template.spec.containers
    volumes = {volume["name"]: volume for volume in job.spec.template.spec.volumes}
    env_vars = {
        env["name"]: env["value"] for env in job_controller.env if "value" in env
    }
    volume_mounts = {
        volume_mount["name"]: volume_mount["mountPath"]
        for volume_mount in job_controller.volume_mounts
    }

    assert job.spec.template.spec.security_context.fs_group == int(
        WORKFLOW_RUNTIME_USER_GID
    )
    assert (
        job.spec.template.spec.security_context.fs_group_change_policy
        == REANA_RUNTIME_FS_GROUP_CHANGE_POLICY
    )
    assert workflow_engine.security_context.run_as_user == int(
        WORKFLOW_RUNTIME_USER_UID
    )
    assert workflow_engine.security_context.run_as_group == int(
        WORKFLOW_RUNTIME_USER_GID
    )
    assert workflow_engine.security_context.run_as_non_root is True
    assert workflow_engine.security_context.allow_privilege_escalation is False
    assert workflow_engine.security_context.capabilities.drop == ["ALL"]
    assert workflow_engine.security_context.seccomp_profile.type == "RuntimeDefault"
    assert job_controller.security_context.run_as_user == int(WORKFLOW_RUNTIME_USER_UID)
    assert job_controller.security_context.run_as_group == int(
        WORKFLOW_RUNTIME_USER_GID
    )
    assert job_controller.security_context.run_as_non_root is True
    assert job_controller.security_context.allow_privilege_escalation is False
    assert job_controller.security_context.capabilities.drop == ["ALL"]
    assert job_controller.security_context.seccomp_profile.type == "RuntimeDefault"
    assert job_controller.args == ["exec python3 -m reana_job_controller.nss_wrapper"]
    assert env_vars["USER"] == "reana"
    assert env_vars["CERN_USER"] == "reana"
    assert env_vars["K8S_USE_SECURITY_CONTEXT"] == "True"
    assert env_vars["NSS_WRAPPER_PASSWD"] == "/var/run/nss_wrapper/passwd"
    assert env_vars["NSS_WRAPPER_GROUP"] == "/var/run/nss_wrapper/group"
    assert env_vars["WORKFLOW_RUNTIME_USER_UID"] == str(WORKFLOW_RUNTIME_USER_UID)
    assert env_vars["WORKFLOW_RUNTIME_USER_GID"] == str(WORKFLOW_RUNTIME_USER_GID)
    assert env_vars["WORKFLOW_RUNTIME_USER_NAME"] == "reana"
    assert env_vars["WORKFLOW_RUNTIME_GROUP_NAME"] == "root"
    assert "nss-wrapper" in volumes
    assert volumes["nss-wrapper"]["emptyDir"] == {}
    assert "uwsgi-config-reana-job-controller" in volumes
    assert volume_mounts["nss-wrapper"] == "/var/run/nss_wrapper"
    assert volume_mounts["uwsgi-config-reana-job-controller"] == "/var/reana/uwsgi"


def test_create_job_spec_skips_security_context_when_disabled(
    sample_serial_workflow_in_db, mock_user_secrets, monkeypatch
):
    """Test that OpenShift-style deployments can disable explicit security contexts."""
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager.K8S_USE_SECURITY_CONTEXT",
        False,
    )
    kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
    job = kwrm._create_job_spec("run-batch-test")

    workflow_engine, job_controller = job.spec.template.spec.containers
    env_vars = {
        env["name"]: env["value"] for env in job_controller.env if "value" in env
    }
    volume_mounts = {
        volume_mount["name"]: volume_mount["mountPath"]
        for volume_mount in job_controller.volume_mounts
    }
    volumes = {volume["name"]: volume for volume in job.spec.template.spec.volumes}

    assert job.spec.template.spec.security_context is None
    assert workflow_engine.security_context is None
    assert job_controller.security_context is None
    assert env_vars["USER"] == "reana"
    assert env_vars["CERN_USER"] == "reana"
    assert env_vars["K8S_USE_SECURITY_CONTEXT"] == "False"
    assert env_vars["NSS_WRAPPER_PASSWD"] == "/var/run/nss_wrapper/passwd"
    assert env_vars["NSS_WRAPPER_GROUP"] == "/var/run/nss_wrapper/group"
    assert "nss-wrapper" in volumes
    assert "uwsgi-config-reana-job-controller" in volumes
    assert volume_mounts["nss-wrapper"] == "/var/run/nss_wrapper"
    assert volume_mounts["uwsgi-config-reana-job-controller"] == "/var/reana/uwsgi"


def test_create_job_spec_drops_colliding_job_controller_env_vars(
    sample_serial_workflow_in_db, mock_user_secrets, monkeypatch, caplog
):
    """Test that Helm passthrough env vars cannot override controller-managed ones."""
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager.JOB_CONTROLLER_ENV_VARS",
        [
            {"name": "WORKFLOW_RUNTIME_USER_UID", "value": "4321"},
            {"name": "NSS_WRAPPER_PASSWD", "value": "/tmp/custom-passwd"},
            {"name": "EXTRA_OPERATOR_VAR", "value": "ok"},
            {"name": "workflow_runtime_user_uid", "value": "case-sensitive"},
        ],
    )
    caplog.set_level("WARNING")

    kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
    job = kwrm._create_job_spec("run-batch-test")

    _, job_controller = job.spec.template.spec.containers
    env_names = [env["name"] for env in job_controller.env]
    env_vars = {
        env["name"]: env["value"] for env in job_controller.env if "value" in env
    }

    assert env_names.count("WORKFLOW_RUNTIME_USER_UID") == 1
    assert env_names.count("NSS_WRAPPER_PASSWD") == 1
    assert env_vars["WORKFLOW_RUNTIME_USER_UID"] == str(WORKFLOW_RUNTIME_USER_UID)
    assert env_vars["NSS_WRAPPER_PASSWD"] == "/var/run/nss_wrapper/passwd"
    assert env_vars["EXTRA_OPERATOR_VAR"] == "ok"
    assert env_vars["workflow_runtime_user_uid"] == "case-sensitive"
    warning_messages = [record.getMessage() for record in caplog.records]
    assert any("WORKFLOW_RUNTIME_USER_UID" in message for message in warning_messages)
    assert any("NSS_WRAPPER_PASSWD" in message for message in warning_messages)
    assert not any(
        "workflow_runtime_user_uid" in message for message in warning_messages
    )
