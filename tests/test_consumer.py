# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller consumer tests."""

import pytest
from kubernetes.client.rest import ApiException
from mock import Mock, patch
from reana_commons.config import MQ_DEFAULT_QUEUES
from reana_commons.consumer import BaseConsumer
from reana_commons.publisher import WorkflowStatusPublisher
from reana_commons.k8s.secrets import UserSecrets, Secret
from reana_db.models import RunStatus

from reana_workflow_controller.consumer import JobStatusConsumer, _update_commit_status


def test_workflow_finish_and_kubernetes_not_available(
    in_memory_queue_connection,
    sample_serial_workflow_in_db,
    consume_queue,
):
    """Test workflow finish with a Kubernetes connection troubles."""
    sample_serial_workflow_in_db.status = RunStatus.running
    next_status = RunStatus.failed
    job_status_consumer = JobStatusConsumer(connection=in_memory_queue_connection)
    workflow_status_publisher = WorkflowStatusPublisher(
        connection=in_memory_queue_connection, queue=job_status_consumer.queue
    )
    workflow_status_publisher.publish_workflow_status(
        str(sample_serial_workflow_in_db.id_),
        next_status.value,
    )
    k8s_corev1_api_client_mock = Mock()
    k8s_corev1_api_client_mock.delete_namespaced_job = Mock(
        side_effect=ApiException(reason="Could not delete job.", status=404)
    )
    with patch(
        "reana_workflow_controller.consumer.current_k8s_corev1_api_client",
        k8s_corev1_api_client_mock,
    ):
        consume_queue(job_status_consumer, limit=1)
    assert sample_serial_workflow_in_db.status == next_status


@pytest.mark.parametrize(
    "status,gitlab_status",
    [
        (RunStatus.created, "running"),
        (RunStatus.deleted, "canceled"),
        (RunStatus.failed, "failed"),
        (RunStatus.finished, "success"),
        (RunStatus.pending, "running"),
        (RunStatus.queued, "running"),
        (RunStatus.running, "running"),
        (RunStatus.stopped, "canceled"),
    ],
)
def test_update_commit_status(
    session, sample_serial_workflow_in_db, status, gitlab_status
):
    """Test update commit status."""
    workflow = sample_serial_workflow_in_db
    workflow.git_repo = "foo/bar"
    session.add(workflow)
    session.commit()

    post_mock = Mock()
    post_mock.return_value.status_code = 200
    secrets = UserSecrets(
        user_id=str(workflow.owner_id),
        k8s_secret_name="k8s-secret",
        secrets=[Secret(name="gitlab_access_token", type_="env", value="my-token")],
    )
    fetch_mock = Mock()
    fetch_mock.return_value = secrets
    with patch("requests.post", post_mock), patch(
        "reana_commons.k8s.secrets.UserSecretsStore.fetch", fetch_mock
    ):
        _update_commit_status(workflow, status)
        fetch_mock.assert_called_once_with(workflow.owner_id)
        post_mock.assert_called_once()
        url = post_mock.call_args.args[0]
        assert "access_token=my-token" in url
        assert f"state={gitlab_status}" in url


def test_update_commit_status_without_token(session, sample_serial_workflow_in_db):
    """Test updating commit status without valid GitLab token."""
    workflow = sample_serial_workflow_in_db
    workflow.git_repo = "foo/bar"
    session.add(workflow)
    session.commit()

    post_mock = Mock()
    secrets = UserSecrets(
        user_id=str(workflow.owner_id),
        k8s_secret_name="k8s-secret",
    )
    fetch_mock = Mock()
    fetch_mock.return_value = secrets
    with patch("requests.post", post_mock), patch(
        "reana_commons.k8s.secrets.UserSecretsStore.fetch", fetch_mock
    ):
        _update_commit_status(workflow, RunStatus.finished)
        fetch_mock.assert_called_once_with(workflow.owner_id)
        post_mock.assert_not_called()
