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
from reana_commons.k8s.secrets import Secret, UserSecrets, UserSecretsStore
from reana_db.database import Session
from reana_db.models import (
    RunStatus,
    InteractiveSession,
    InteractiveSessionType,
)

from reana_workflow_controller.config import (
    REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS,
    REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD,
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
    assert job_controller.lifecycle.pre_stop.http_get is None
    shutdown_command = job_controller.lifecycle.pre_stop._exec.command
    assert shutdown_command[:2] == ["python3", "-c"]
    assert "http://127.0.0.1:5000/shutdown" in shutdown_command[2]
    # The loopback shutdown call must not honour a site-injected proxy env
    # var (HTTP_PROXY/http_proxy) -- it must use an opener with an explicit
    # empty ProxyHandler, not the bare (proxy-aware) urlopen default.
    assert "urllib.request.ProxyHandler({})" in shutdown_command[2]
    assert "urllib.request.urlopen(" not in shutdown_command[2]
    # The timeout must match the pod's own termination grace period, not a
    # shorter hardcoded value that could cut /shutdown off before it
    # finished stopping every job.
    assert (
        f"timeout={REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD})"
        in shutdown_command[2]
    )
    # A failure here (e.g. job-controller already gone, a common, benign
    # teardown case) must not fail the hook -- the pod deletion it guards
    # must proceed regardless.
    assert "except Exception" in shutdown_command[2]
    compile(shutdown_command[2], "<pre_stop_exec>", "exec")
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
    assert job.spec.template.spec.automount_service_account_token is False
    assert "job-controller-service-account" not in {
        mount["name"] for mount in workflow_engine.volume_mounts
    }
    assert volume_mounts["job-controller-service-account"] == (
        "/var/run/secrets/kubernetes.io/serviceaccount"
    )
    projected_sources = volumes["job-controller-service-account"]["projected"][
        "sources"
    ]
    assert volumes["job-controller-service-account"]["projected"]["defaultMode"] == 420
    assert projected_sources[0]["serviceAccountToken"] == {
        "path": "token",
        "expirationSeconds": 3600,
    }
    assert projected_sources[1]["configMap"]["name"] == "kube-root-ca.crt"
    # An absent ConfigMap must not wedge every batch pod in ContainerCreating.
    assert projected_sources[1]["configMap"]["optional"] is True
    assert projected_sources[2]["downwardAPI"]["items"][0]["path"] == "namespace"
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


def _user_secrets_with(monkeypatch, secrets):
    """Make the secret store of the workflow owner return the given secrets."""
    user_secrets = UserSecrets(
        user_id="00000000-0000-0000-0000-000000000000",
        k8s_secret_name="k8s-secret",
        secrets=secrets,
    )
    monkeypatch.setattr(UserSecretsStore, "fetch", lambda _: user_secrets)
    return user_secrets


def test_create_job_spec_keeps_user_secrets_out_of_job_controller_env(
    sample_serial_workflow_in_db, monkeypatch
):
    """Test that only supported credential secrets reach the trusted sidecar."""
    _user_secrets_with(
        monkeypatch,
        [
            Secret(name="BASH_ENV", type_="env", value="/var/reana/x.sh"),
            Secret(name="LD_PRELOAD", type_="env", value="/var/reana/x.so"),
            Secret(name="LIBNSS_WRAPPER_PATH", type_="env", value="/x.so"),
            Secret(name="PYTHONPATH", type_="env", value="/var/reana"),
            Secret(name="REANA_USER_ID", type_="env", value="victim-uuid"),
            Secret(name="REANA_JOB_HOSTPATH_MOUNTS", type_="env", value="[]"),
            Secret(name="K8S_USE_SECURITY_CONTEXT", type_="env", value="False"),
            Secret(
                name="REANA_KUBERNETES_JOBS_MAX_USER_CPU_LIMIT",
                type_="env",
                value="1000",
            ),
            Secret(
                name="REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
                type_="env",
                value="False",
            ),
            Secret(
                name="REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT",
                type_="env",
                value="1000Ti",
            ),
            Secret(name="MY_APP_TOKEN", type_="env", value="dummy"),
            Secret(name="VONAME", type_="env", value="atlas"),
            Secret(name="CERN_KEYTAB", type_="env", value="dummy.keytab"),
            Secret(name="CERN_USER", type_="env", value="dummyuser"),
            Secret(name="dummy.keytab", type_="file", value=b"dummy"),
        ],
    )
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager."
        "REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
        True,
    )
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager."
        "REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT",
        "2Gi",
    )
    kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
    job = kwrm._create_job_spec("run-batch-test")

    workflow_engine, job_controller = job.spec.template.spec.containers
    env_names = [env["name"] for env in job_controller.env]
    env_vars = {
        env["name"]: env["value"] for env in job_controller.env if "value" in env
    }
    secret_env_names = {env["name"] for env in job_controller.env if "valueFrom" in env}

    # Provenance, not only names: only allowed names come from the secret store.
    assert secret_env_names == {"VONAME", "CERN_KEYTAB"}
    for name in (
        "BASH_ENV",
        "LD_PRELOAD",
        "LIBNSS_WRAPPER_PATH",
        "PYTHONPATH",
        "MY_APP_TOKEN",
    ):
        assert name not in env_names
    for name in (
        "REANA_USER_ID",
        "REANA_JOB_HOSTPATH_MOUNTS",
        "K8S_USE_SECURITY_CONTEXT",
        "REANA_KUBERNETES_JOBS_MAX_USER_CPU_LIMIT",
        "REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
        "REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT",
        "CERN_USER",
    ):
        assert env_names.count(name) == 1
    assert env_vars["REANA_USER_ID"] == str(sample_serial_workflow_in_db.owner_id)
    assert env_vars["K8S_USE_SECURITY_CONTEXT"] == "True"
    assert env_vars["REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM"] == "True"
    assert env_vars["REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT"] == "2Gi"
    assert env_vars["CERN_USER"] == "dummyuser"
    assert env_vars["USER"] == "dummyuser"
    # The workflow engine never receives user secrets.
    assert not any("valueFrom" in env for env in workflow_engine.env)
    # File secrets are still mounted for the job controller.
    volumes = {volume["name"]: volume for volume in job.spec.template.spec.volumes}
    assert volumes["k8s-secret"]["secret"]["items"] == [
        {"key": "dummy.keytab", "path": "dummy.keytab"}
    ]


@pytest.mark.parametrize(
    "cern_user",
    ["bad:user", "bad\nroot:x:0:0::/:/bin/sh", "alice\n", "", "-rf", "a" * 33, "$(id)"],
)
def test_create_job_spec_ignores_invalid_cern_user(
    sample_serial_workflow_in_db, monkeypatch, cern_user
):
    """Test that a malformed CERN_USER secret cannot reach passwd or HTCondor."""
    _user_secrets_with(
        monkeypatch, [Secret(name="CERN_USER", type_="env", value=cern_user)]
    )
    kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
    job = kwrm._create_job_spec("run-batch-test")

    _, job_controller = job.spec.template.spec.containers
    env_vars = {
        env["name"]: env["value"] for env in job_controller.env if "value" in env
    }
    assert env_vars["CERN_USER"] == "reana"
    assert env_vars["USER"] == "reana"


def test_interactive_session_uses_per_session_secret(sample_serial_workflow_in_db):
    """Per-session token is stored in a Secret, not in the pod arguments."""
    with patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_corev1_api_client=DEFAULT,
        current_k8s_networking_api_client=DEFAULT,
        current_k8s_appsv1_api_client=DEFAULT,
    ) as mocks:
        kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
        kwrm.start_interactive_session(
            InteractiveSessionType(0).name, expose_secrets=False
        )
        int_session = sample_serial_workflow_in_db.sessions[0]
        secret = int_session.session_secret
        assert secret
        assert len(secret) >= 32
        secret_call = mocks[
            "current_k8s_corev1_api_client"
        ].create_namespaced_secret.call_args
        secret_object = secret_call.args[1]
        assert secret_object.string_data == {
            "notebook_args": "--NotebookApp.token={}".format(secret)
        }
        deployment_call = mocks[
            "current_k8s_appsv1_api_client"
        ].create_namespaced_deployment.call_args
        deployment = deployment_call.args[1]
        container = deployment.spec.template.spec.containers[0]
        assert secret not in repr(deployment)
        assert all("NotebookApp.token" not in arg for arg in container.args)
        token_env = next(env for env in container.env if env.name == "NOTEBOOK_ARGS")
        assert token_env.value is None
        assert token_env.value_from.secret_key_ref.name == secret_object.metadata.name
        assert token_env.value_from.secret_key_ref.key == "notebook_args"


@pytest.mark.parametrize("read_only", [False, True])
def test_create_job_spec_read_only_root_filesystem(
    sample_serial_workflow_in_db, mock_user_secrets, monkeypatch, read_only
):
    """Test that the read-only flag shapes the workflow-engine container."""
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager."
        "REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
        read_only,
    )
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager."
        "REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT",
        "2Gi",
    )
    monkeypatch.setattr(
        "reana_workflow_controller.k8s."
        "REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT",
        "2Gi",
    )
    kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
    job = kwrm._create_job_spec("run-batch-test")

    pod_spec = job.spec.template.spec
    engine, sidecar = pod_spec.containers
    sidecar_env = {env["name"]: env["value"] for env in sidecar.env if "value" in env}
    engine_mounts = {vm["name"]: vm for vm in engine.volume_mounts}
    pod_volumes = {v["name"]: v for v in pod_spec.volumes}

    # the flag and the size limit are always forwarded to the job-controller
    # sidecar so the wfc -> r-j-c hop cannot silently break
    assert sidecar_env["REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM"] == str(
        read_only
    )
    assert sidecar_env["REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT"] == "2Gi"
    # the restricted security context is kept in both cases
    assert engine.security_context.run_as_non_root is True
    assert engine.security_context.capabilities.drop == ["ALL"]

    if read_only:
        assert engine.security_context.read_only_root_filesystem is True
        # the engine command is left untouched; scratch is provided as
        # size-limited emptyDir mounts at the standard locations
        assert engine_mounts["reana-engine-tmp"]["mountPath"] == "/tmp"
        assert engine_mounts["reana-engine-cache"]["mountPath"] == "/.cache"
        assert pod_volumes["reana-engine-tmp"]["emptyDir"] == {"sizeLimit": "2Gi"}
        assert pod_volumes["reana-engine-cache"]["emptyDir"] == {"sizeLimit": "2Gi"}
        # the job-controller sidecar is deliberately left writable and does
        # not receive the scratch mounts
        assert sidecar.security_context.read_only_root_filesystem is None
        sidecar_mounts = {vm["name"] for vm in sidecar.volume_mounts}
        assert "reana-engine-tmp" not in sidecar_mounts
    else:
        assert engine.security_context.read_only_root_filesystem is None
        assert "reana-engine-tmp" not in engine_mounts
        assert "reana-engine-cache" not in engine_mounts
        assert "reana-engine-tmp" not in pod_volumes


def test_create_job_spec_read_only_without_security_context(
    sample_serial_workflow_in_db, mock_user_secrets, monkeypatch
):
    """The read-only flag still applies when security contexts are disabled."""
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager.K8S_USE_SECURITY_CONTEXT",
        False,
    )
    monkeypatch.setattr(
        "reana_workflow_controller.workflow_run_manager."
        "REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
        True,
    )
    kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
    job = kwrm._create_job_spec("run-batch-test")

    engine, sidecar = job.spec.template.spec.containers

    assert engine.security_context.read_only_root_filesystem is True
    assert engine.security_context.run_as_user is None
    assert sidecar.security_context is None


@pytest.mark.parametrize(
    "environment,declared_repos,expected_repos",
    [
        ("docker.io/library/busybox", [], []),
        ("docker.io/library/busybox", ["sft.cern.ch"], ["sft.cern.ch"]),
        (
            "/cvmfs/unpacked.cern.ch/registry.hub.docker.com/library/python:3.11",
            [],
            ["unpacked.cern.ch"],
        ),
        (
            "/cvmfs/unpacked.cern.ch/registry.hub.docker.com/library/python:3.11",
            ["sft.cern.ch", "unpacked.cern.ch"],
            ["sft.cern.ch", "unpacked.cern.ch"],
        ),
        ("images/my_tool.sif", [], []),
    ],
)
def test_retrieve_required_cvmfs_repos_includes_unpacked_images(
    environment, declared_repos, expected_repos
):
    """Test that CVMFS repositories of unpacked images are mounted automatically."""
    workflow = Mock()
    workflow.reana_specification = {
        "workflow": {
            "type": "serial",
            "resources": {"cvmfs": declared_repos},
            "specification": {
                "steps": [{"environment": environment, "commands": ["ls"]}]
            },
        }
    }
    kwrm = KubernetesWorkflowRunManager(workflow)
    assert kwrm.retrieve_required_cvmfs_repos() == expected_repos
