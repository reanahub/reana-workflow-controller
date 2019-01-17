# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Workflow run manager for Kubernetes backends."""

from kubernetes import client

from reana_commons.k8s.api_client import current_k8s_batchv1_api_client
from reana_workflow_controller.config import (MANILA_CEPHFS_PVC,
                                              SHARED_FS_MAPPING,
                                              REANA_STORAGE_BACKEND,
                                              TTL_SECONDS_AFTER_FINISHED)
from reana_workflow_controller.workflow_run_managers import WorkflowRunManager


class KubernetesWorkflowRunManager(WorkflowRunManager):
    """Implementation of WorkflowRunManager for Kubernetes."""

    k8s_shared_volume = {
        'ceph': {
            'name': 'default-shared-volume',
            'persistentVolumeClaim': {
                'claimName': MANILA_CEPHFS_PVC,
                'readOnly': False,
            }
        },
        'local': {
            'name': 'default-shared-volume',
            'hostPath': {
                'path': SHARED_FS_MAPPING['MOUNT_SOURCE_PATH'],
            }
        }
    }
    """Configuration to connect to the different storage backends."""

    def start_batch_workflow_run(self):
        """Start a batch workflow run."""
        namespace = 'default'
        workflow_name = self._workflow_run_name_generator('batch')
        job = self._create_job_spec(workflow_name)
        current_k8s_batchv1_api_client.create_namespaced_job(
            namespace=namespace, body=job)

    def _create_job_spec(self, name, command=None, image=None,
                         env_vars=None):
        """Instantiate a Kubernetes job.

        :param name: Name of the job.
        :param image: Docker image to use to run the job on.
        :param command: List of commands to run on the given job.
        :param env_vars: List of environment variables (dictionaries) to
            inject into the workflow engine container.
        """
        image = image or self._workflow_engine_image()
        command = command or self._workflow_engine_command()
        env_vars = env_vars or self._workflow_engine_env_vars()
        if isinstance(command, str):
            command = [command]
        elif not isinstance(command, list):
            raise ValueError('Command should be a list or a string and not {}'
                             .format(type(command)))

        workflow_metadata = client.V1ObjectMeta(name=name)
        job = client.V1Job()
        job.api_version = 'batch/v1'
        job.kind = 'Job'
        job.metadata = workflow_metadata
        spec = client.V1JobSpec(
            template=client.V1PodTemplateSpec())
        spec.template.metadata = workflow_metadata
        container = client.V1Container(name=name, image=image,
                                       image_pull_policy='IfNotPresent',
                                       env=[], volume_mounts=[],
                                       command=['/bin/bash', '-c'],
                                       args=command)
        container.env.extend(env_vars)
        container.volume_mounts = [
            {
                'name': 'default-shared-volume',
                'mountPath': SHARED_FS_MAPPING['MOUNT_DEST_PATH'],
            },
        ]
        spec.template.spec = client.V1PodSpec(containers=[container])
        spec.template.spec.volumes = [
            KubernetesWorkflowRunManager.k8s_shared_volume
            [REANA_STORAGE_BACKEND]
        ]
        job.spec = spec
        job.spec.template.spec.restart_policy = 'Never'
        job.spec.ttl_seconds_after_finished = TTL_SECONDS_AFTER_FINISHED
        job.spec.backoff_limit = 0
        return job
