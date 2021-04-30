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
from reana_db.models import RunStatus

from reana_workflow_controller.consumer import JobStatusConsumer


def test_workflow_finish_and_kubernetes_not_available(
    in_memory_queue_connection, sample_serial_workflow_in_db, consume_queue,
):
    """Test workflow finish with a Kubernetes connection troubles."""
    sample_serial_workflow_in_db.status = RunStatus.running
    next_status = RunStatus.failed
    job_status_consumer = JobStatusConsumer(connection=in_memory_queue_connection)
    workflow_status_publisher = WorkflowStatusPublisher(
        connection=in_memory_queue_connection, queue=job_status_consumer.queue
    )
    workflow_status_publisher.publish_workflow_status(
        str(sample_serial_workflow_in_db.id_), next_status.value,
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
