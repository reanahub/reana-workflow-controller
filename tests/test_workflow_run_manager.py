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
from reana_workflow_controller.errors import REANAInteractiveSessionError
from reana_workflow_controller.workflow_run_manager import \
    KubernetesWorkflowRunManager


def test_start_interactive_session(sample_serial_workflow_in_db):
    """Test interactive workflow run deployment."""
    with patch.multiple("reana_workflow_controller.k8s",
                        current_k8s_corev1_api_client=DEFAULT,
                        current_k8s_extensions_v1beta1=DEFAULT) as mocks:
        kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
        if len(INTERACTIVE_SESSION_TYPES):
            kwrm.start_interactive_session(INTERACTIVE_SESSION_TYPES[0])
        mocks['current_k8s_extensions_v1beta1'].\
            create_namespaced_deployment.assert_called_once()
        mocks['current_k8s_corev1_api_client'].\
            create_namespaced_service.assert_called_once()
        mocks['current_k8s_extensions_v1beta1'].\
            create_namespaced_ingress.assert_called_once()


def test_start_interactive_workflow_k8s_failure(sample_serial_workflow_in_db):
    """Test failure of an interactive workflow run deployment because of ."""
    mocked_k8s_client = Mock()
    mocked_k8s_client.create_namespaced_deployment =\
        Mock(side_effect=ApiException(reason='some reason'))
    with patch.multiple('reana_workflow_controller.k8s',
                        current_k8s_extensions_v1beta1=mocked_k8s_client,
                        current_k8s_corev1_api_client=DEFAULT):
        with pytest.raises(REANAInteractiveSessionError,
                           match=r'.*Kubernetes has failed.*'):
            kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
            if len(INTERACTIVE_SESSION_TYPES):
                kwrm.start_interactive_session(INTERACTIVE_SESSION_TYPES[0])


def test_atomic_creation_of_interactive_session(sample_serial_workflow_in_db):
    """Test the correct creation of all objects related to an interactive
       sesison as well as writing the state to DB, either all should be done
       or nothing.."""
    mocked_k8s_client = Mock()
    mocked_k8s_client.create_namespaced_deployment =\
        Mock(side_effect=ApiException(
             reason='Error while creating deployment'))
    # Raise 404 when deleting Deployment, because it doesn't exist
    mocked_k8s_client.delete_namespaced_deployment =\
        Mock(side_effect=ApiException(
             reason='Not Found'))
    with patch.multiple('reana_workflow_controller.k8s',
                        current_k8s_extensions_v1beta1=mocked_k8s_client,
                        current_k8s_corev1_api_client=DEFAULT) as mocks:
        try:
            kwrm = KubernetesWorkflowRunManager(sample_serial_workflow_in_db)
            if len(INTERACTIVE_SESSION_TYPES):
                kwrm.start_interactive_session(INTERACTIVE_SESSION_TYPES[0])
        except REANAInteractiveSessionError:
            mocks['current_k8s_corev1_api_client']\
                .delete_namespaced_service.assert_called_once()
            mocked_k8s_client.delete_namespaced_ingress.assert_called_once()
            mocked_k8s_client.delete_namespaced_deployment.assert_called_once()
            assert sample_serial_workflow_in_db.interactive_session is None
