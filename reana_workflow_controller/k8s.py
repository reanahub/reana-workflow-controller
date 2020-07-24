# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller Kubernetes utils."""

import os

from kubernetes import client
from kubernetes.client.rest import ApiException
from reana_commons.config import (
    CVMFS_REPOSITORIES,
    REANA_WORKFLOW_UMASK,
    REANA_RUNTIME_KUBERNETES_NODE_LABEL,
)
from reana_commons.k8s.api_client import (
    current_k8s_appsv1_api_client,
    current_k8s_corev1_api_client,
    current_k8s_networking_v1beta1,
)
from reana_commons.k8s.volumes import get_k8s_cvmfs_volume, get_shared_volume

from reana_workflow_controller.config import (  # isort:skip
    JUPYTER_INTERACTIVE_SESSION_DEFAULT_IMAGE,
    JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT,
    SHARED_VOLUME_PATH,
)


class InteractiveDeploymentK8sBuilder(object):
    """Build Kubernetes deployment objects for interactive sessions."""

    internal_service_port = 8081
    """Port exposed by the Service placed in front of the Deployment and
       referenced by the Ingress. This port has nothing to do with the
       port exposed by deployment itself, the one which can change
       from one interactive session application to other."""

    def __init__(self, deployment_name, workspace, image, port, path, cvmfs_repos=None):
        """Initialise basic interactive deployment builder for Kubernetes.

        :param deployment_name: Name which identifies all deployment objects
            and maps to the workflow it belongs.
        :param workspace: Path to the interactive session workspace, which
            matches with the workflow workspace the interactive session
            belongs to.
        :param image: Docker image which the deployment will use as base.
        :param port: Port exposed by the Docker image.
        :param path: Path where the interactive session will be accessible
            from outside the cluster.
        """
        self.deployment_name = deployment_name
        self.workspace = workspace
        self.image = image
        self.port = port
        self.path = path
        self.cvmfs_repos = cvmfs_repos or []
        metadata = client.V1ObjectMeta(
            name=deployment_name, labels={"reana_workflow_mode": "session"},
        )
        self.kubernetes_objects = {
            "ingress": self._build_ingress(metadata),
            "service": self._build_service(metadata),
            "deployment": self._build_deployment(metadata),
        }

    def _build_ingress(self, metadata):
        """Build ingress Kubernetes object.

        :param metadata: Common Kubernetes metadata for the interactive
            deployment.
        """
        ingress_backend = client.NetworkingV1beta1IngressBackend(
            service_name=self.deployment_name,
            service_port=InteractiveDeploymentK8sBuilder.internal_service_port,
        )
        ingress_rule_value = client.NetworkingV1beta1HTTPIngressRuleValue(
            [
                client.NetworkingV1beta1HTTPIngressPath(
                    path=self.path, backend=ingress_backend
                )
            ]
        )
        spec = client.NetworkingV1beta1IngressSpec(
            rules=[client.NetworkingV1beta1IngressRule(http=ingress_rule_value)]
        )
        ingress = client.NetworkingV1beta1Ingress(
            api_version="networking.k8s.io/v1beta1",
            kind="Ingress",
            spec=spec,
            metadata=metadata,
        )
        return ingress

    def _build_service(self, metadata):
        """Build service Kubernetes object.

        :param metadata: Common Kubernetes metadata for the interactive
            deployment.
        """
        spec = client.V1ServiceSpec(
            type="NodePort",
            ports=[
                client.V1ServicePort(
                    port=InteractiveDeploymentK8sBuilder.internal_service_port,
                    target_port=self.port,
                )
            ],
            selector={"app": self.deployment_name},
        )
        service = client.V1beta1APIService(
            api_version="v1", kind="Service", spec=spec, metadata=metadata,
        )
        return service

    def _build_deployment(self, metadata):
        """Build deployment Kubernetes object.

        :param metadata: Common Kubernetes metadata for the interactive
            deployment.
        """
        container = client.V1Container(name=self.deployment_name, image=self.image)
        pod_spec = client.V1PodSpec(
            containers=[container], node_selector=REANA_RUNTIME_KUBERNETES_NODE_LABEL
        )
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": self.deployment_name}),
            spec=pod_spec,
        )
        spec = client.V1DeploymentSpec(
            selector=client.V1LabelSelector(match_labels={"app": self.deployment_name}),
            replicas=1,
            template=template,
        )
        deployment = client.V1Deployment(
            api_version="apps/v1", kind="Deployment", metadata=metadata, spec=spec,
        )

        return deployment

    def add_command(self, command):
        """Add a command to the deployment."""
        self.kubernetes_objects["deployment"].spec.template.spec.containers[
            0
        ].command = command

    def add_command_arguments(self, args):
        """Add command line arguments in addition to the command."""
        self.kubernetes_objects["deployment"].spec.template.spec.containers[
            0
        ].args = args

    def add_reana_shared_storage(self):
        """Add the REANA shared file system volume mount to the deployment."""
        volume_mount, volume = get_shared_volume(self.workspace)
        self.kubernetes_objects["deployment"].spec.template.spec.containers[
            0
        ].volume_mounts = [volume_mount]
        self.kubernetes_objects["deployment"].spec.template.spec.volumes = [volume]

    def _build_cvmfs_volume_mount(self, cvmfs_repos):
        """Build the Volume and VolumeMount necessary to enable CVMFS.

        :param cvmfs_mounts: List of CVMFS repos to make available. They
            should be part of ``reana_commons.config.CVMFS_REPOSITORIES``.
        """
        cvmfs_map = {}
        volumes = []
        volume_mounts = []
        for repo in cvmfs_repos:
            if repo in CVMFS_REPOSITORIES:
                cvmfs_map[CVMFS_REPOSITORIES[repo]] = repo

        for repo_name, path in cvmfs_map.items():
            volume = get_k8s_cvmfs_volume(repo_name)
            volumes.append(volume)
            volume_mounts.append(
                {
                    "name": volume["name"],
                    "mountPath": "/cvmfs/{}".format(path),
                    "readOnly": volume["readOnly"],
                }
            )

        return volumes, volume_mounts

    def add_cvmfs_repo_mounts(self, cvmfs_repos):
        """Add mounts for the provided CVMFS repositories to the deployment.

        :param cvmfs_mounts: List of CVMFS repos to make available. They
            should be part of ``reana_commons.config.CVMFS_REPOSITORIES``.
        """
        cvmfs_volumes, cvmfs_volume_mounts = self._build_cvmfs_volume_mount(cvmfs_repos)
        self.kubernetes_objects["deployment"].spec.template.spec.volumes.extend(
            cvmfs_volumes
        )
        self.kubernetes_objects["deployment"].spec.template.spec.containers[
            0
        ].volume_mounts.extend(cvmfs_volume_mounts)

    def add_environment_variable(self, name, value):
        """Add an environment variable.

        :param name: Environment variable name.
        :param value: Environment variable value.
        """
        env_var = client.V1EnvVar(name, str(value))
        if isinstance(
            self.kubernetes_objects["deployment"].spec.template.spec.containers[0].env,
            list,
        ):
            self.kubernetes_objects["deployment"].spec.template.spec.containers[
                0
            ].env.append(env_var)
        else:
            self.kubernetes_objects["deployment"].spec.template.spec.containers[
                0
            ].env = [env_var]

    def add_run_with_root_permissions(self):
        """Run interactive session with root."""
        security_context = client.V1SecurityContext(run_as_user=0)
        self.kubernetes_objects["deployment"].spec.template.spec.containers[
            0
        ].security_context = security_context

    def get_deployment_objects(self):
        """Return the alrady built Kubernetes objects."""
        return self.kubernetes_objects


def build_interactive_jupyter_deployment_k8s_objects(
    deployment_name,
    workspace,
    access_path,
    access_token=None,
    cvmfs_repos=None,
    image=None,
):
    """Build the Kubernetes specification for a Jupyter NB interactive session.

    :param deployment_name: Name used to tag all Kubernetes objects spawned
        for the given interactive session.
    :param workspace: Path to the interactive session workspace, which
        matches with the workflow workspace the interactive session
        belongs to.
    :param access_path: URL path where the interactive session will be
        accessible. Note that this path should be set as base path of
        the interactive session service whenever redirections are needed,
        i.e. if we expose ``/1234`` and then application does a redirect to
        /me Traefik won't send the request to the interactive session
        (``/1234/me``) but to the root path (``/me``) giving most probably
        a ``404``.
    :param cvmfs_mounts: List of CVMFS repos to make available. They
        should be part of ``reana_commons.config.CVMFS_REPOSITORIES``.
    :param image: Jupyter Notebook image to use, i.e.
        ``jupyter/tensorflow-notebook`` to enable ``tensorflow``.
    """
    image = image or JUPYTER_INTERACTIVE_SESSION_DEFAULT_IMAGE
    cvmfs_repos = cvmfs_repos or []
    port = JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT
    deployment_builder = InteractiveDeploymentK8sBuilder(
        deployment_name, workspace, image, port, access_path
    )
    command_args = [
        "start-notebook.sh",
        "--NotebookApp.base_url='{base_url}'".format(base_url=access_path),
        "--notebook-dir='{workflow_workspace}'".format(
            workflow_workspace=os.path.join(SHARED_VOLUME_PATH, workspace)
        ),
    ]
    if access_token:
        command_args.append(
            "--NotebookApp.token='{access_token}'".format(access_token=access_token)
        )
    deployment_builder.add_command_arguments(command_args)
    deployment_builder.add_reana_shared_storage()
    if cvmfs_repos:
        deployment_builder.add_cvmfs_repo_mounts(cvmfs_repos)
    deployment_builder.add_environment_variable("NB_GID", 0)
    # Changes umask so all files generated by the Jupyter Notebook can be
    # modified by the root group users.
    deployment_builder.add_environment_variable("NB_UMASK", REANA_WORKFLOW_UMASK)
    deployment_builder.add_run_with_root_permissions()
    return deployment_builder.get_deployment_objects()


build_interactive_k8s_objects = {
    "jupyter": build_interactive_jupyter_deployment_k8s_objects
}
"""Build interactive k8s deployment objects."""


def instantiate_chained_k8s_objects(kubernetes_objects, namespace):
    """Instantiate chained Kubernetes objects.

    :param kubernetes_objects: Dictionary composed by the object kind as
        key and the object itself as value.
    :param namespace: Kubernetes namespace where the objects will be deployed.
    """
    instantiate_k8s_object = {
        "deployment": current_k8s_appsv1_api_client.create_namespaced_deployment,
        "service": current_k8s_corev1_api_client.create_namespaced_service,
        "ingress": current_k8s_networking_v1beta1.create_namespaced_ingress,
    }
    try:
        parent_k8s_object_references = None
        for index, obj in enumerate(kubernetes_objects.items()):
            kind = obj[0]
            k8s_object = obj[1]
            if index == 0:
                result = instantiate_k8s_object[kind](namespace, k8s_object)
                parent_k8s_object_references = [
                    {
                        "uid": result._metadata.uid,
                        "kind": result._kind,
                        "name": result._metadata.name,
                        "apiVersion": result._api_version,
                    }
                ]
            else:
                k8s_object.metadata.owner_references = parent_k8s_object_references
                result = instantiate_k8s_object[kind](namespace, k8s_object)
    except KeyError:
        raise Exception("Unsupported Kubernetes object kind {}.".format(kind))
    except ApiException as e:
        raise ApiException(
            "Exception when calling ExtensionsV1beta1Api->"
            "create_namespaced_deployment_rollback: {}\n".format(e)
        )


def delete_k8s_objects_if_exist(kubernetes_objects, namespace):
    """Delete Kubernetes objects if they exist.

    :param kubernetes_objects: Dictionary composed by the object kind as
        key and the object itself as value.
    :param namespace: Kubernetes namespace where the objects will be deleted
        from.
    """
    delete_k8s_object = {
        "deployment": current_k8s_appsv1_api_client.delete_namespaced_deployment,
        "service": current_k8s_corev1_api_client.delete_namespaced_service,
        "ingress": current_k8s_networking_v1beta1.delete_namespaced_ingress,
    }
    try:
        for obj in kubernetes_objects.items():
            try:
                kind = obj[0]
                k8s_object = obj[1]
                delete_k8s_object[kind](k8s_object.metadata.name, namespace)
            except ApiException as k8s_api_exception:
                if k8s_api_exception.reason == "Not Found":
                    continue
                else:
                    raise
    except KeyError:
        raise Exception("Unsupported Kubernetes object kind {}.".format(kind))


def delete_k8s_ingress_object(ingress_name, namespace):
    """Delete Kubernetes ingress object.

    :param ingress_name: name of ingress object to delete.
    :param namespace: k8s namespace of ingress object.
    """
    try:
        current_k8s_networking_v1beta1.delete_namespaced_ingress(
            name=ingress_name, namespace=namespace, body=client.V1DeleteOptions()
        )
    except ApiException as k8s_api_exception:
        if k8s_api_exception.reason == "Not Found":
            raise Exception("K8s object was not found {}.".format(ingress_name))
        raise Exception(
            "Exception when calling ExtensionsV1beta1->"
            "Api->delete_namespaced_ingress: {}\n".format(k8s_api_exception)
        )
