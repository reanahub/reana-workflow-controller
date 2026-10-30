# This file is part of REANA.
# Copyright (C) 2024, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from kubernetes import client
import pytest
from reana_commons.config import WORKFLOW_RUNTIME_USER_GID, WORKFLOW_RUNTIME_USER_UID
from reana_commons.k8s.secrets import Secret, UserSecrets, UserSecretsStore
from reana_workflow_controller.config import (
    REANA_RUNTIME_FS_GROUP_CHANGE_POLICY,
    REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS,
)
from reana_workflow_controller.errors import ReservedEnvironmentVariableError
from reana_workflow_controller.k8s import (
    InteractiveDeploymentK8sBuilder,
    build_interactive_jupyter_deployment_k8s_objects,
    delete_k8s_objects_if_exist,
    get_compatible_kerberos_k8s_config,
    instantiate_chained_k8s_objects,
    limit_credential_cache_volumes,
)


def test_session_secret_is_supported_by_create_and_delete(monkeypatch):
    """Session lifecycle creates and deletes per-session Secret objects."""
    create_secret = Mock(
        return_value=SimpleNamespace(
            _metadata=SimpleNamespace(uid="uid", name="session-auth"),
            _kind="Secret",
            _api_version="v1",
        )
    )
    delete_secret = Mock()
    monkeypatch.setattr(
        "reana_workflow_controller.k8s.current_k8s_corev1_api_client",
        SimpleNamespace(
            create_namespaced_secret=create_secret,
            delete_namespaced_secret=delete_secret,
            create_namespaced_service=Mock(),
            delete_namespaced_service=Mock(),
        ),
    )
    monkeypatch.setattr(
        "reana_workflow_controller.k8s.current_k8s_appsv1_api_client",
        SimpleNamespace(
            create_namespaced_deployment=Mock(),
            delete_namespaced_deployment=Mock(),
        ),
    )
    monkeypatch.setattr(
        "reana_workflow_controller.k8s.current_k8s_networking_api_client",
        SimpleNamespace(
            create_namespaced_ingress=Mock(),
            delete_namespaced_ingress=Mock(),
        ),
    )
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(name="session-auth"),
        string_data={"notebook_args": "--NotebookApp.token=not-in-a-pod-spec"},
    )

    instantiate_chained_k8s_objects({"secret": secret}, "default")
    delete_k8s_objects_if_exist({"secret": secret}, "default")

    create_secret.assert_called_once_with("default", secret)
    delete_secret.assert_called_once_with("session-auth", "default")


def test_interactive_deployment_k8s_builder_user_secrets(monkeypatch):
    """Expose user secrets in interactive sessions"""
    user_id = uuid4()
    user_secrets = UserSecrets(
        user_id=str(user_id),
        k8s_secret_name="k8s-secret",
        secrets=[Secret(name="third_env", type_="env", value="3")],
    )
    monkeypatch.setattr(
        UserSecretsStore,
        "fetch",
        lambda _: user_secrets,
    )

    builder = InteractiveDeploymentK8sBuilder(
        "name", "workflow_id", "owner_id", "workspace", "docker_image", "port", "path"
    )

    builder.add_command_arguments(["args"])
    builder.add_reana_shared_storage()
    builder.add_user_secrets()
    builder.add_environment_variable("first_env", "1")
    builder.add_environment_variable("second_env", "2")
    builder.add_run_with_runtime_user_permissions()
    objs = builder.get_deployment_objects()

    deployment = objs["deployment"]
    pod = deployment.spec.template.spec
    assert len(pod.containers) == 1
    assert any(v["name"] == "k8s-secret" for v in pod.volumes)
    assert any(
        vm["name"] == "k8s-secret" for vm in pod.containers[0].volume_mounts)
    assert any(e["name"] == "third_env" for e in pod.containers[0].env)
    assert pod.security_context.fs_group == int(WORKFLOW_RUNTIME_USER_GID)
    assert (
        pod.security_context.fs_group_change_policy
        == REANA_RUNTIME_FS_GROUP_CHANGE_POLICY
    )
    assert (
        pod.security_context.supplemental_groups
        == REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS
    )
    assert pod.containers[0].security_context.run_as_user == int(
        WORKFLOW_RUNTIME_USER_UID
    )
    assert pod.containers[0].security_context.run_as_group == int(
        WORKFLOW_RUNTIME_USER_GID
    )
    assert pod.containers[0].security_context.run_as_non_root is True
    assert pod.containers[0].security_context.allow_privilege_escalation is False
    assert pod.containers[0].security_context.capabilities.drop == ["ALL"]
    assert pod.containers[0].security_context.seccomp_profile.type == "RuntimeDefault"


@pytest.mark.parametrize("reserved_name", ["NOTEBOOK_ARGS", "REANA_WORKSPACE"])
def test_interactive_deployment_rejects_reserved_user_secret(
    monkeypatch, reserved_name
):
    """User secrets cannot replace controller-managed session configuration.

    A colliding secret must reject session start with a clear error, not
    silently drop the user's secret: a dropped secret produces no signal
    anywhere the user or an admin would see it, leaving it permanently and
    invisibly excluded from every future interactive session.
    """
    user_secrets = UserSecrets(
        user_id="owner_id",
        k8s_secret_name="k8s-secret",
        secrets=[
            Secret(name=reserved_name, type_="env", value="override"),
            Secret(name="own_env", type_="env", value="kept"),
        ],
    )
    monkeypatch.setattr(UserSecretsStore, "fetch", lambda _: user_secrets)
    builder = InteractiveDeploymentK8sBuilder(
        "name", "workflow_id", "owner_id", "workspace", "image", 8080, "/path"
    )
    builder.add_session_secret("notebook-session-secret")

    with pytest.raises(ReservedEnvironmentVariableError, match=reserved_name):
        builder.add_user_secrets()


def test_interactive_deployment_k8s_builder_skips_security_context_when_disabled(
    monkeypatch,
):
    """Do not force interactive-session UID/GID when disabled."""
    monkeypatch.setattr(
        "reana_workflow_controller.k8s.K8S_USE_SECURITY_CONTEXT", False)

    builder.add_run_with_runtime_user_permissions()

    assert (
        builder.get_deployment_objects()[
            "deployment"
        ].spec.template.spec.security_context
        is None
    )
    assert (
        builder.get_deployment_objects()["deployment"]
        .spec.template.spec.containers[0]
        .security_context
        is None
    )


def test_interactive_deployment_k8s_builder_omits_empty_supplemental_groups(
    monkeypatch,
):
    """Do not serialise supplementalGroups when the config is empty."""
    monkeypatch.setattr(
        "reana_workflow_controller.k8s.REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS",
        [],
    )

    builder = InteractiveDeploymentK8sBuilder(
        "name", "workflow_id", "owner_id", "workspace", "docker_image", "port", "path"
    )

    assert builder.get_deployment_objects()[
        "deployment"
    ].spec.template.spec.security_context.supplemental_groups in (None, [])


def test_get_compatible_kerberos_k8s_config_supports_old_commons_api(monkeypatch):
    """Retry Kerberos config calls without the new optional kwarg when needed."""
    calls = []

    def old_get_kerberos_k8s_config(user_secrets, kubernetes_uid):
        calls.append((user_secrets, kubernetes_uid))
        return "kerberos-config"

    monkeypatch.setattr(
        "reana_workflow_controller.k8s.get_kerberos_k8s_config",
        old_get_kerberos_k8s_config,
    )

    kerberos_config = get_compatible_kerberos_k8s_config("secrets", 1000)

    assert kerberos_config == "kerberos-config"
    assert calls == [("secrets", 1000)]


def test_get_compatible_kerberos_k8s_config_backfills_partial_security_context(
    monkeypatch,
):
    """Backfill missing PSA fields from released commons Kerberos specs."""

    def partially_hardened_get_kerberos_k8s_config(
        user_secrets, kubernetes_uid, use_security_context=True
    ):
        return SimpleNamespace(
            init_container={
                "securityContext": {
                    "runAsUser": int(kubernetes_uid),
                    "runAsNonRoot": True,
                }
            },
            renew_container={
                "securityContext": {
                    "runAsUser": int(kubernetes_uid),
                    "runAsNonRoot": True,
                }
            },
        )

    monkeypatch.setattr(
        "reana_workflow_controller.k8s.get_kerberos_k8s_config",
        partially_hardened_get_kerberos_k8s_config,
    )

    kerberos_config = get_compatible_kerberos_k8s_config("secrets", 1000)

    expected_security_context = {
        "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
        "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert (
        kerberos_config.init_container["securityContext"] == expected_security_context
    )
    assert (
        kerberos_config.renew_container["securityContext"] == expected_security_context
    )


def _build_jupyter_session(monkeypatch, read_only, size_limit="5Gi"):
    """Build a Jupyter interactive session pod spec with the given flag."""
    monkeypatch.setattr(
        "reana_workflow_controller.k8s."
        "REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
        read_only,
    )
    monkeypatch.setattr(
        "reana_workflow_controller.k8s."
        "REANA_KUBERNETES_JOBS_SCRATCH_VOLUME_SIZE_LIMIT",
        size_limit,
    )
    objs = build_interactive_jupyter_deployment_k8s_objects(
        "session-name",
        "/workspace",
        "/access-path",
        "docker.io/jupyter/scipy-notebook",
        "notebook-session-secret",
        owner_id=str(uuid4()),
        workflow_id=str(uuid4()),
        expose_secrets=False,
    )
    return objs["deployment"].spec.template.spec


@pytest.mark.parametrize(
    "size_limit, expected_empty_dir",
    [("5Gi", {"sizeLimit": "5Gi"}), ("", {})],
)
def test_interactive_session_read_only_root_filesystem_enabled(
    monkeypatch, size_limit, expected_empty_dir
):
    """Jupyter session gets ephemeral scratch and a writable home."""
    pod_spec = _build_jupyter_session(
        monkeypatch, read_only=True, size_limit=size_limit
    )
    container = pod_spec.containers[0]
    env = {e.name: e.value for e in container.env}
    mounts = {vm["name"]: vm for vm in container.volume_mounts}
    volumes = {v["name"]: v for v in pod_spec.volumes}

    assert container.security_context.read_only_root_filesystem is True
    # the read-only flag must not replace the restricted security context
    assert container.security_context.run_as_non_root is True
    assert container.security_context.capabilities.drop == ["ALL"]
    # HOME points at a writable emptyDir, from which Jupyter/ipython/pip
    # derive their cache, runtime and config directories
    assert env["HOME"] == "/home/reana"
    assert mounts["reana-session-home"]["mountPath"] == "/home/reana"
    assert mounts["reana-session-tmp"]["mountPath"] == "/tmp"
    assert volumes["reana-session-home"]["emptyDir"] == expected_empty_dir
    assert volumes["reana-session-tmp"]["emptyDir"] == expected_empty_dir
    # the default startup command is preserved (no wrapper)
    assert container.args[0] == "start-notebook.sh"


def test_interactive_session_read_only_root_filesystem_disabled(monkeypatch):
    """Without the flag the session keeps its default home and no scratch."""
    pod_spec = _build_jupyter_session(monkeypatch, read_only=False)
    container = pod_spec.containers[0]
    env = {e.name: e.value for e in container.env}
    mount_names = {vm["name"] for vm in container.volume_mounts}

    assert container.security_context.read_only_root_filesystem is None
    assert "HOME" not in env
    assert "reana-session-tmp" not in mount_names
    assert "reana-session-home" not in mount_names
    assert container.args[0] == "start-notebook.sh"


def test_interactive_session_read_only_without_security_context(monkeypatch):
    """The read-only flag still applies when security contexts are disabled."""
    monkeypatch.setattr(
        "reana_workflow_controller.k8s.K8S_USE_SECURITY_CONTEXT", False)
    pod_spec = _build_jupyter_session(monkeypatch, read_only=True)
    security_context = pod_spec.containers[0].security_context

    assert security_context.read_only_root_filesystem is True
    assert security_context.run_as_user is None


@pytest.mark.parametrize("read_only", [False, True])
def test_limit_credential_cache_volumes(monkeypatch, read_only):
    """Credential caches are size-limited only in read-only root pods."""
    monkeypatch.setattr(
        "reana_workflow_controller.k8s.REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
        read_only,
    )
    volumes = [
        {"name": "krb5-cache", "emptyDir": {}},
        {"name": "krb5-conf", "configMap": {"name": "krb5-conf"}},
    ]

    limit_credential_cache_volumes(volumes)

    expected_empty_dir = {"sizeLimit": "10Mi"} if read_only else {}
    assert volumes[0]["emptyDir"] == expected_empty_dir
    # volumes that are not emptyDir volumes are not changed
    assert volumes[1] == {"name": "krb5-conf",
                          "configMap": {"name": "krb5-conf"}}


def test_s3_integration(monkeypatch):
    """Checks datastore sidecar creation and env variables allocation between pods."""
    user_id = uuid4()
    user_secrets = UserSecrets(
        user_id=str(user_id),
        k8s_secret_name="k8s-secret",
        secrets=[
            Secret(name="main_env", type_="env", value="3"),
            Secret(name="S3_TO_LOCAL_TEST_ALIAS", type_="env", value="TEST"),
            Secret(name="S3_TO_LOCAL_TEST_ACCESS_KEY", type_="env", value="-"),
            Secret(name="S3_TO_LOCAL_TEST_BUCKET", type_="env", value="-"),
            Secret(name="S3_TO_LOCAL_TEST_HOST", type_="env", value="-"),
            Secret(name="S3_TO_LOCAL_TEST_SECRET_KEY", type_="env", value="-"),
            Secret(name="S3_TO_LOCAL_TEST_REGION", type_="env", value="-"),
        ],
    )
    monkeypatch.setattr(
        UserSecretsStore,
        "fetch",
        lambda _: user_secrets,
    )

    monkeypatch.setattr(
        "reana_workflow_controller.k8s.REANA_DATASTORE_ENABLED", True)

    builder = InteractiveDeploymentK8sBuilder(
        "name", "workflow_id", "owner_id", "workspace", "docker_image", "port", "path"
    )
    builder.add_user_secrets()
    builder.add_run_with_root_permissions()
    builder.setup_s3_sidecar()
    builder.setup_s3_storage()
    objs = builder.get_deployment_objects()

    deployment = objs["deployment"]
    pod = deployment.spec.template.spec
    assert len(pod.containers) == 2
    assert any(e["name"] == "main_env" for e in pod.containers[0].env)
    assert any(
        e["name"] == "S3_TO_LOCAL_TEST_ALIAS" for e in pod.containers[1].env)
    assert len(pod.containers[1].env) == 6
