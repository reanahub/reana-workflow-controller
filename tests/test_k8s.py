# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from reana_commons.config import WORKFLOW_RUNTIME_USER_GID, WORKFLOW_RUNTIME_USER_UID
from reana_workflow_controller.config import (
    REANA_RUNTIME_FS_GROUP_CHANGE_POLICY,
    REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS,
)
from reana_workflow_controller.k8s import (
    InteractiveDeploymentK8sBuilder,
    get_compatible_kerberos_k8s_config,
)
from reana_commons.k8s.secrets import UserSecretsStore, UserSecrets, Secret


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
    assert any(vm["name"] == "k8s-secret" for vm in pod.containers[0].volume_mounts)
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


def test_interactive_deployment_k8s_builder_skips_security_context_when_disabled(
    monkeypatch,
):
    """Do not force interactive-session UID/GID when disabled."""
    monkeypatch.setattr("reana_workflow_controller.k8s.K8S_USE_SECURITY_CONTEXT", False)

    builder = InteractiveDeploymentK8sBuilder(
        "name", "workflow_id", "owner_id", "workspace", "docker_image", "port", "path"
    )

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


def test_interactive_deployment_k8s_builder_filtered_user_secrets(monkeypatch):
    """Expose only the explicitly allowed user secrets in interactive sessions."""
    user_id = uuid4()
    user_secrets = UserSecrets(
        user_id=str(user_id),
        k8s_secret_name="k8s-secret",
        secrets=[
            Secret(name="wanted_env", type_="env", value="1"),
            Secret(name="other_env", type_="env", value="2"),
            Secret(name="wanted_file", type_="file", value="secret file"),
        ],
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
    builder.add_user_secrets(secret_names=["wanted_env", "wanted_file"])
    objs = builder.get_deployment_objects()

    pod = objs["deployment"].spec.template.spec
    secret_volume = next(
        volume for volume in pod.volumes if volume["name"] == "k8s-secret"
    )
    env_names = {env_var["name"] for env_var in pod.containers[0].env}

    assert "wanted_env" in env_names
    assert "other_env" not in env_names
    assert secret_volume["secret"]["items"] == [
        {"key": "wanted_file", "path": "wanted_file"}
    ]


def test_interactive_deployment_k8s_builder_without_user_secrets(monkeypatch):
    """Expose no user secrets when the allowlist is explicitly empty."""
    user_id = uuid4()
    user_secrets = UserSecrets(
        user_id=str(user_id),
        k8s_secret_name="k8s-secret",
        secrets=[Secret(name="wanted_env", type_="env", value="1")],
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
    builder.add_user_secrets(secret_names=[])
    objs = builder.get_deployment_objects()

    pod = objs["deployment"].spec.template.spec

    assert not any(v["name"] == "k8s-secret" for v in pod.volumes)
    assert not any(vm["name"] == "k8s-secret" for vm in pod.containers[0].volume_mounts)
    assert not any(e["name"] == "wanted_env" for e in pod.containers[0].env)
