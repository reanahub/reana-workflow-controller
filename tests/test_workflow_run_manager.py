# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Workflow-Controller WorkflowRunManager tests."""

from __future__ import absolute_import, print_function

import pytest
from kubernetes.client.rest import ApiException
from mock import DEFAULT, Mock, patch

from reana_commons.config import KRB5_INIT_CONTAINER_NAME
from reana_db.models import (
    RunStatus,
    InteractiveSession,
    InteractiveSessionType,
)

from reana_workflow_controller.config import (
    REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS,
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
            assert not sample_serial_workflow_in_db.sessions.all()


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

            int_session = InteractiveSession.query.filter_by(
                owner_id=workflow.owner_id,
                type_=InteractiveSessionType(0).name,
            ).first()
            assert int_session.status == RunStatus.created
            kwrm.stop_interactive_session(int_session.id_)
            assert not workflow.sessions.first()


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

    volumes = [volume["name"] for volume in job.spec.template.spec.volumes]
    assert len(set(volumes)) == len(volumes)  # volumes have unique names
    assert any(volume.startswith("reana-secretsstore") for volume in volumes)
    assert "krb5-cache" in volumes
    assert "krb5-conf" in volumes
