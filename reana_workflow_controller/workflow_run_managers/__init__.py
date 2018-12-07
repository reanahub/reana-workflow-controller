# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Workflow run manager interface."""

from reana_workflow_controller.config import WORKFLOW_ENGINE_VERSION


class WorkflowRunManager():
    """Interface which specifies how to manage workflow runs."""

    common_env_variables = [
        {
            'name': 'ZMQ_PROXY_CONNECT',
            'value': 'tcp://zeromq-msg-proxy.default.svc.cluster.local:8666'
        },
        {
            'name': 'SHARED_VOLUME_PATH',
            'value': '/reana'
        }
    ]
    """Common to all workflow engines environment variables."""

    engine_mapping = {
        'cwl': {'image': 'reanahub/reana-workflow-engine-cwl:{}'.format(
            WORKFLOW_ENGINE_VERSION),
                'command': ['sleep', '1000'],
                'environment_variables': common_env_variables},
        'yadage': {'image': 'reanahub/reana-workflow-engine-yadage:{}'.format(
            WORKFLOW_ENGINE_VERSION),
                   'command': ['sleep', '1000'],
                   'environment_variables': common_env_variables},
        'serial': {'image': 'reanahub/reana-workflow-engine-serial:{}'.format(
            WORKFLOW_ENGINE_VERSION),
                   'command': ['sleep', '1000'],
                   'environment_variables': common_env_variables},
    }
    """Mapping between engines and their basis configuration."""

    def __init__(self, workflow):
        """Initialise a WorkflowRunManager.

        :param workflow: An instance of :class:`reana_db.models.Workflow`.
        """
        self.workflow = workflow

    def _workflow_run_name_generator(self, mode):
        """Generate the name to be given to a workflow run.

        In the case of Kubernetes, this should allow administrators to be able
        to easily find workflow runs i.e.:
        .. code-block:: console

           $ kubectl get pods | grep batch
           batch-serial-64594f48ff-5mgbz  0/1  Running 0   1m
           batch-cwl-857bb969bb-john-64f97d955d-jklcw  0/1  Running 0  16h

           $ kubectl get pods | grep interactive
           interactive-yadage-7fbb558577-xdxn8  0/1  Running  0  30m

        :param mode: Mode in which the workflow runs, like ``batch`` or
            ``interactive``.
        """
        return '{mode}-{workflow_type}-{workflow_id}'.format(
            mode=mode,
            workflow_id=self.workflow.id_,
            workflow_type=self.workflow.type_,
        )

    def start_batch_workflow_run(self):
        """Start a batch workflow run."""
        raise NotImplementedError('')

    def _workflow_engine_image(self):
        """Return the correct image for the current workflow type."""
        return WorkflowRunManager.engine_mapping[self.workflow.type_]['image']

    def _workflow_engine_command(self):
        """Return the command to be run for a given workflow engine."""
        return (WorkflowRunManager.engine_mapping[self.workflow.type_]
                ['command'])

    def _workflow_engine_env_vars(self):
        """Return necessary environment variables for the workflow engine."""
        return (WorkflowRunManager.engine_mapping[self.workflow.type_]
                ['environment_variables'])
