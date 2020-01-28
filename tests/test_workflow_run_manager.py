# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Workflow-Controller WorkflowRunManager tests."""

from __future__ import absolute_import, print_function

from string import Template

import pkg_resources
import pytest
from kubernetes.client.rest import ApiException
from mock import DEFAULT, Mock, patch
from reana_commons.config import INTERACTIVE_SESSION_TYPES
from reana_db.models import WorkflowStatus

from reana_workflow_controller.errors import REANAInteractiveSessionError
from reana_workflow_controller.workflow_run_manager import \
    KubernetesWorkflowRunManager


def test_start_interactive_session(sample_serial_workflow_in_db):
    """Test interactive workflow run deployment."""
    with patch.multiple("reana_workflow_controller.k8s",
                        current_k8s_corev1_api_client=DEFAULT,
                        current_k8s_networking_v1beta1=DEFAULT,
                        current_k8s_appsv1_api_client=DEFAULT) as mocks:
        kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
        if len(INTERACTIVE_SESSION_TYPES):
            kwrm.start_interactive_session(INTERACTIVE_SESSION_TYPES[0])
        mocks['current_k8s_appsv1_api_client'].\
            create_namespaced_deployment.assert_called_once()
        mocks['current_k8s_corev1_api_client'].\
            create_namespaced_service.assert_called_once()
        mocks['current_k8s_networking_v1beta1'].\
            create_namespaced_ingress.assert_called_once()


def test_start_interactive_workflow_k8s_failure(sample_serial_workflow_in_db):
    """Test failure of an interactive workflow run deployment because of ."""
    mocked_k8s_client = Mock()
    mocked_k8s_client.create_namespaced_deployment =\
        Mock(side_effect=ApiException(reason='some reason'))
    with patch.multiple('reana_workflow_controller.k8s',
                        current_k8s_appsv1_api_client=mocked_k8s_client,
                        current_k8s_corev1_api_client=DEFAULT,
                        current_k8s_networking_v1beta1=DEFAULT):
        with pytest.raises(REANAInteractiveSessionError,
                           match=r'.*Kubernetes has failed.*'):
            kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
            if len(INTERACTIVE_SESSION_TYPES):
                kwrm.start_interactive_session(INTERACTIVE_SESSION_TYPES[0])


def test_atomic_creation_of_interactive_session(sample_serial_workflow_in_db):
    """Test atomic creation of interactive sessions.

    All interactive session should be created as  well as writing the state
    to DB, either all should be done or nothing.
    """
    mocked_k8s_client = Mock()
    mocked_k8s_client.create_namespaced_deployment =\
        Mock(side_effect=ApiException(
             reason='Error while creating deployment'))
    # Raise 404 when deleting Deployment, because it doesn't exist
    mocked_k8s_client.delete_namespaced_deployment =\
        Mock(side_effect=ApiException(
             reason='Not Found'))
    with patch.multiple('reana_workflow_controller.k8s',
                        current_k8s_appsv1_api_client=mocked_k8s_client,
                        current_k8s_networking_v1beta1=DEFAULT,
                        current_k8s_corev1_api_client=DEFAULT) as mocks:
        try:
            kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
            if len(INTERACTIVE_SESSION_TYPES):
                kwrm.start_interactive_session(INTERACTIVE_SESSION_TYPES[0])
        except REANAInteractiveSessionError:
            mocks['current_k8s_corev1_api_client']\
                .delete_namespaced_service.assert_called_once()
            mocks['current_k8s_networking_v1beta1']\
                .delete_namespaced_ingress.assert_called_once()
            mocked_k8s_client.delete_namespaced_deployment.assert_called_once()
            assert sample_serial_workflow_in_db.interactive_session is None


def test_stop_workflow_backend_only_kubernetes(
        sample_serial_workflow_in_db,
        add_kubernetes_jobs_to_workflow):
    """Test deletion of workflows with only Kubernetes based jobs."""
    workflow = sample_serial_workflow_in_db
    workflow.status = WorkflowStatus.running
    workflow_jobs = add_kubernetes_jobs_to_workflow(workflow)
    backend_job_ids = [job.backend_job_id for job in workflow_jobs]
    with patch("reana_workflow_controller.workflow_run_manager."
               "current_k8s_batchv1_api_client") as api_client:
        kwrm = KubernetesWorkflowRunManager(workflow)
        kwrm.stop_batch_workflow_run()
        for delete_call in api_client.delete_namespaced_job.call_args_list:
            if delete_call.args[0] in backend_job_ids:
                del backend_job_ids[backend_job_ids.index(
                    delete_call.args[0])]

        assert not backend_job_ids
