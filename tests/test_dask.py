# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

import pytest
from uuid import uuid4

from flask import current_app
from mock import patch, MagicMock


from reana_workflow_controller.dask import requires_dask


@pytest.mark.parametrize(
    "workflow_fixture, expected_result",
    [
        ("sample_serial_workflow_in_db", False),
        ("sample_serial_workflow_in_db_with_dask", True),
    ],
)
def test_requires_dask(workflow_fixture, expected_result, request):
    """Test requires_dask with 2 workflows one of which uses Dask and other not."""
    workflow = request.getfixturevalue(workflow_fixture)
    result = requires_dask(workflow)
    assert (
        result == expected_result
    ), f"Expected requires_dask to return {expected_result} for {workflow_fixture}"


def test_create_dask_cluster(mock_k8s_client, dask_resource_manager):
    """Test creation of dask cluster."""
    # Arrange
    dask_resource_manager.cluster_body = {"mock": "cluster_body"}

    # Act
    dask_resource_manager._create_dask_cluster()

    # Assert
    mock_k8s_client.create_namespaced_custom_object.assert_called_once_with(
        group="kubernetes.dask.org",
        version="v1",
        plural="daskclusters",
        namespace="default",
        body={"mock": "cluster_body"},
    )


def test_create_dask_autoscaler(
    mock_k8s_client, dask_resource_manager, mock_user_secrets
):
    """Test creation of dask autoscaler."""
    # Arrange
    dask_resource_manager.autoscaler_body = {"mock": "autoscaler_body"}

    # Act
    dask_resource_manager._create_dask_autoscaler()

    # Assert
    mock_k8s_client.create_namespaced_custom_object.assert_called_once_with(
        group="kubernetes.dask.org",
        version="v1",
        plural="daskautoscalers",
        namespace="default",
        body={"mock": "autoscaler_body"},
    )


def test_add_image_pull_secrets(dask_resource_manager):
    """Test _add_image_pull_secrets function."""
    # Arrange
    with patch.object(current_app, "config", {"IMAGE_PULL_SECRETS": ["my-secret"]}):
        dask_resource_manager.cluster_body = {
            "spec": {
                "worker": {"spec": {"containers": [{}]}},
                "scheduler": {"spec": {"containers": [{}]}},
            }
        }

        # Act
        dask_resource_manager._add_image_pull_secrets()

        # Assert
        expected_image_pull_secrets = [{"name": "my-secret"}]
        assert (
            dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["containers"][
                0
            ]["imagePullSecrets"]
            == expected_image_pull_secrets
        )
        assert (
            dask_resource_manager.cluster_body["spec"]["scheduler"]["spec"][
                "containers"
            ][0]["imagePullSecrets"]
            == expected_image_pull_secrets
        )


def test_add_hostpath_volumes_with_mounts(
    mock_k8s_client, dask_resource_manager, mock_user_secrets
):
    """Test _add_hostpath_volumes function."""
    REANA_JOB_HOSTPATH_MOUNTS = [
        {
            "name": "volume1",
            "hostPath": "/host/path/volume1",
            "mountPath": "/container/path/volume1",
        },
        {
            "name": "volume2",
            "hostPath": "/host/path/volume2",
        },
    ]
    # Arrange
    with patch(
        "reana_workflow_controller.dask.REANA_JOB_HOSTPATH_MOUNTS",
        REANA_JOB_HOSTPATH_MOUNTS,
    ):
        dask_resource_manager.cluster_body = {
            "spec": {
                "worker": {
                    "spec": {"containers": [{"volumeMounts": []}], "volumes": []}
                },
            }
        }

        # Act
        dask_resource_manager._add_hostpath_volumes()

        # Assert
        expected_volume_mounts = [
            {"name": "volume1", "mountPath": "/container/path/volume1"},
            {
                "name": "volume2",
                "mountPath": "/host/path/volume2",
            },
        ]
        expected_volumes = [
            {"name": "volume1", "hostPath": {"path": "/host/path/volume1"}},
            {"name": "volume2", "hostPath": {"path": "/host/path/volume2"}},
        ]
        assert (
            dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["containers"][
                0
            ]["volumeMounts"]
            == expected_volume_mounts
        )
        assert (
            dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["volumes"]
            == expected_volumes
        )


def test_create_dask_resources(dask_resource_manager):
    """Test create_dask_resources method."""
    # Patch internal methods that should be called
    with patch.object(
        dask_resource_manager, "_prepare_cluster"
    ) as mock_prepare_cluster, patch.object(
        dask_resource_manager, "_create_dask_cluster"
    ) as mock_create_cluster, patch.object(
        dask_resource_manager, "_create_dask_autoscaler"
    ) as mock_create_autoscaler, patch(
        "reana_workflow_controller.dask.create_dask_dashboard_ingress"
    ) as mock_create_dashboard_ingress:

        # Act
        dask_resource_manager.create_dask_resources()

        # Assert
        mock_prepare_cluster.assert_called_once()
        mock_create_cluster.assert_called_once()
        mock_create_autoscaler.assert_called_once()
        mock_create_dashboard_ingress.assert_called_once_with(
            dask_resource_manager.workflow_id
        )


def test_add_workspace_volume(dask_resource_manager):
    """Test _add_workspace_volume method."""
    # Mock the get_workspace_volume function
    with patch(
        "reana_workflow_controller.dask.get_workspace_volume"
    ) as mock_get_workspace_volume, patch.object(
        dask_resource_manager, "_add_volumes"
    ) as mock_add_volumes:

        mock_volume_mount = {"name": "workspace-volume-mount"}
        mock_volume = {"name": "workspace-volume"}
        mock_get_workspace_volume.return_value = (mock_volume_mount, mock_volume)

        # Act
        dask_resource_manager._add_workspace_volume()

        # Assert
        mock_get_workspace_volume.assert_called_once_with(
            dask_resource_manager.workflow_workspace
        )
        mock_add_volumes.assert_called_once_with([(mock_volume_mount, mock_volume)])


def test_add_eos_volume_when_eos_is_available(dask_resource_manager):
    """Test _add_eos_volume method when EOS is available."""
    # Mock the configuration and the method _add_volumes
    with patch("reana_workflow_controller.dask.K8S_CERN_EOS_AVAILABLE", True), patch(
        "reana_workflow_controller.dask.K8S_CERN_EOS_MOUNT_CONFIGURATION",
        {
            "volumeMounts": {"name": "eos-volume-mount"},
            "volume": {"name": "eos-volume"},
        },
    ), patch.object(dask_resource_manager, "_add_volumes") as mock_add_volumes:

        # Act
        dask_resource_manager._add_eos_volume()

        # Assert
        mock_add_volumes.assert_called_once_with(
            [({"name": "eos-volume-mount"}, {"name": "eos-volume"})]
        )


def test_add_eos_volume_when_eos_is_not_available(dask_resource_manager):
    """Test _add_eos_volume method when EOS is not available."""
    with patch(
        "reana_workflow_controller.dask.K8S_CERN_EOS_AVAILABLE", False
    ), patch.object(dask_resource_manager, "_add_volumes") as mock_add_volumes:

        # Act
        dask_resource_manager._add_eos_volume()

        # Assert
        mock_add_volumes.assert_not_called()


def test_add_shared_volume_not_already_added(dask_resource_manager):
    """Test _add_shared_volume when shared volume is not already in the list."""
    with patch(
        "reana_workflow_controller.dask.get_reana_shared_volume"
    ) as mock_get_shared_volume:

        mock_shared_volume = {"name": "shared-volume"}
        mock_get_shared_volume.return_value = mock_shared_volume

        dask_resource_manager.cluster_body = {
            "spec": {"worker": {"spec": {"volumes": []}}}
        }

        # Act
        dask_resource_manager._add_shared_volume()

        # Assert
        assert (
            mock_shared_volume
            in dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["volumes"]
        )
        mock_get_shared_volume.assert_called_once()


def test_add_shared_volume_already_added(dask_resource_manager):
    """Test _add_shared_volume when shared volume is already in the list."""
    with patch(
        "reana_workflow_controller.dask.get_reana_shared_volume"
    ) as mock_get_shared_volume:

        mock_shared_volume = {"name": "shared-volume"}
        mock_get_shared_volume.return_value = mock_shared_volume

        dask_resource_manager.cluster_body = {
            "spec": {
                "worker": {
                    "spec": {
                        "volumes": [
                            mock_shared_volume
                        ]  # Already contains the shared volume
                    }
                }
            }
        }

        # Act
        dask_resource_manager._add_shared_volume()

        # Assert
        assert (
            len(dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["volumes"])
            == 1
        )
        assert (
            dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["volumes"][0]
            == mock_shared_volume
        )
        mock_get_shared_volume.assert_called_once()


def test_add_krb5_containers(dask_resource_manager):
    """Test _add_krb5_containers method."""
    with patch(
        "reana_workflow_controller.dask.get_kerberos_k8s_config"
    ) as mock_get_krb5_config, patch(
        "reana_workflow_controller.dask.KRB5_STATUS_FILE_LOCATION", "/tmp/krb5_status"
    ):

        KRB5_STATUS_FILE_LOCATION = "/tmp/krb5_status"

        mock_krb5_config = MagicMock()
        mock_krb5_config.volumes = [{"name": "krb5-volume"}]
        mock_krb5_config.volume_mounts = [{"mountPath": "/krb5"}]
        mock_krb5_config.env = [{"name": "KRB5CCNAME", "value": "/tmp/krb5cc"}]
        mock_krb5_config.init_container = {"name": "krb5-init-container"}
        mock_krb5_config.renew_container = {"name": "krb5-renew-container"}
        mock_get_krb5_config.return_value = mock_krb5_config

        dask_resource_manager.cluster_body = {
            "spec": {
                "worker": {
                    "spec": {
                        "volumes": [],
                        "containers": [
                            {"volumeMounts": [], "env": [], "args": ["some-command"]}
                        ],
                        "initContainers": [],
                    }
                }
            }
        }

        # Act
        dask_resource_manager._add_krb5_containers()

        # Assert
        assert {"name": "krb5-volume"} in dask_resource_manager.cluster_body["spec"][
            "worker"
        ]["spec"]["volumes"]

        assert {"mountPath": "/krb5"} in dask_resource_manager.cluster_body["spec"][
            "worker"
        ]["spec"]["containers"][0]["volumeMounts"]

        assert {
            "name": "KRB5CCNAME",
            "value": "/tmp/krb5cc",
        } in dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["containers"][
            0
        ][
            "env"
        ]

        assert {"name": "krb5-init-container"} in dask_resource_manager.cluster_body[
            "spec"
        ]["worker"]["spec"]["initContainers"]

        assert {"name": "krb5-renew-container"} in dask_resource_manager.cluster_body[
            "spec"
        ]["worker"]["spec"]["containers"]

        expected_args = [f"trap 'touch {KRB5_STATUS_FILE_LOCATION}' EXIT; some-command"]
        assert (
            dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["containers"][
                0
            ]["args"]
            == expected_args
        )


def test_prepare_cluster(dask_resource_manager):
    """Test _prepare_cluster method."""
    # Mock the private methods that should be called
    with patch.object(
        dask_resource_manager, "_add_image_pull_secrets"
    ) as mock_add_image_pull_secrets, patch.object(
        dask_resource_manager, "_add_hostpath_volumes"
    ) as mock_add_hostpath_volumes, patch.object(
        dask_resource_manager, "_add_workspace_volume"
    ) as mock_add_workspace_volume, patch.object(
        dask_resource_manager, "_add_shared_volume"
    ) as mock_add_shared_volume, patch.object(
        dask_resource_manager, "_add_eos_volume"
    ) as mock_add_eos_volume, patch.object(
        dask_resource_manager.secrets_store, "get_file_secrets_volume_as_k8s_specs"
    ) as mock_get_file_secrets_volume:

        mock_get_file_secrets_volume.return_value = {"name": "secrets-volume"}

        dask_resource_manager.cluster_body = {
            "spec": {
                "worker": {
                    "spec": {
                        "containers": [
                            {"args": ["worker-command"], "env": [], "volumeMounts": []}
                        ],
                        "volumes": [],
                    }
                },
                "scheduler": {
                    "spec": {"containers": [{}]},
                    "service": {"selector": {}},
                },
            }
        }
        dask_resource_manager.autoscaler_body = {"spec": {}}

        # Act
        dask_resource_manager._prepare_cluster()

        # Assert
        mock_add_image_pull_secrets.assert_called_once()
        mock_add_hostpath_volumes.assert_called_once()
        mock_add_workspace_volume.assert_called_once()
        mock_add_shared_volume.assert_called_once()
        mock_add_eos_volume.assert_called_once()

        assert (
            dask_resource_manager.cluster_body["metadata"]["name"]
            == dask_resource_manager.cluster_name
        )

        assert {
            "name": "DASK_SCHEDULER_URI",
            "value": dask_resource_manager.dask_scheduler_uri,
        } in dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["containers"][
            0
        ][
            "env"
        ]

        expected_command = (
            f"cd {dask_resource_manager.workflow_workspace} && worker-command"
        )
        assert (
            dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["containers"][
                0
            ]["args"][0]
            == expected_command
        )

        assert (
            dask_resource_manager.cluster_body["spec"]["worker"]["spec"]["containers"][
                0
            ]["image"]
            == dask_resource_manager.cluster_image
        )
        assert (
            dask_resource_manager.cluster_body["spec"]["scheduler"]["spec"][
                "containers"
            ][0]["image"]
            == dask_resource_manager.cluster_image
        )

        assert (
            dask_resource_manager.secrets_volume_mount
            in dask_resource_manager.cluster_body["spec"]["worker"]["spec"][
                "containers"
            ][0]["volumeMounts"]
        )
        assert {"name": "secrets-volume"} in dask_resource_manager.cluster_body["spec"][
            "worker"
        ]["spec"]["volumes"]

        assert (
            dask_resource_manager.cluster_body["spec"]["scheduler"]["service"][
                "selector"
            ]["dask.org/cluster-name"]
            == dask_resource_manager.cluster_name
        )
