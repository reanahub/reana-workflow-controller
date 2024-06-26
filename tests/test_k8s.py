# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

from unittest.mock import Mock, patch
from reana_workflow_controller.k8s import InteractiveDeploymentK8sBuilder
from reana_commons.k8s.secrets import REANAUserSecretsStore


def test_interactive_deployment_k8s_builder_user_secrets(monkeypatch):
    """Expose user secrets in interactive sessions"""
    monkeypatch.setattr(
        REANAUserSecretsStore,
        "get_file_secrets_volume_as_k8s_specs",
        lambda _: {"name": "secrets-volume"},
    )
    monkeypatch.setattr(
        REANAUserSecretsStore,
        "get_secrets_volume_mount_as_k8s_spec",
        lambda _: {"name": "secrets-volume-mount"},
    )
    monkeypatch.setattr(
        REANAUserSecretsStore,
        "get_env_secrets_as_k8s_spec",
        lambda _: [{"name": "third_env", "value": "3"}],
    )

    builder = InteractiveDeploymentK8sBuilder(
        "name", "workflow_id", "owner_id", "workspace", "docker_image", "port", "path"
    )

    builder.add_command_arguments(["args"])
    builder.add_reana_shared_storage()
    builder.add_user_secrets()
    builder.add_environment_variable("first_env", "1")
    builder.add_environment_variable("second_env", "2")
    builder.add_run_with_root_permissions()
    objs = builder.get_deployment_objects()

    deployment = objs["deployment"]
    pod = deployment.spec.template.spec
    assert len(pod.containers) == 1
    assert {"name": "secrets-volume"} in pod.volumes
    assert {"name": "secrets-volume-mount"} in pod.containers[0].volume_mounts
    assert {"name": "third_env", "value": "3"} in pod.containers[0].env
