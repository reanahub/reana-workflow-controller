# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

from unittest.mock import Mock, patch
from uuid import uuid4

from reana_workflow_controller.k8s import InteractiveDeploymentK8sBuilder
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
    builder.add_run_with_root_permissions()
    objs = builder.get_deployment_objects()

    deployment = objs["deployment"]
    pod = deployment.spec.template.spec
    assert len(pod.containers) == 1
    assert any(v["name"] == "k8s-secret" for v in pod.volumes)
    assert any(vm["name"] == "k8s-secret" for vm in pod.containers[0].volume_mounts)
    assert any(e["name"] == "third_env" for e in pod.containers[0].env)


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

    monkeypatch.setattr("reana_workflow_controller.k8s.REANA_DATASTORE_ENABLED", True)

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
    assert any(e["name"] == "S3_TO_LOCAL_TEST_ALIAS" for e in pod.containers[1].env)
    assert len(pod.containers[1].env) == 6
