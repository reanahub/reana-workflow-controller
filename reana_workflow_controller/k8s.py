# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller Kubernetes utils."""

from kubernetes import client
from reana_commons.k8s.api_client import (current_k8s_corev1_api_client,
                                          current_k8s_extensions_v1beta1)
from reana_workflow_controller.config import (
    JUPYTER_INTERACTIVE_SESSION_DEFAULT_IMAGE,
    JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT
)


class InteractiveDeploymentK8sBuilder(object):
    """Build Kubernetes deployment objects for interactive sessions."""

    internal_service_port = 8081
    """Port exposed by the Service placed in front of the Deployment and
       referenced by the Ingress. This port has nothing to do with the
       port exposed by deployment itself, the one which can change
       from one interactive session application to other."""

    def __init__(self, deployment_name, image, port, path):
        """Initialise basic interactive deployment builder for Kubernetes."""
        self.deployment_name = deployment_name
        self.image = image
        self.port = port
        self.path = path
        metadata = client.V1ObjectMeta(
            name=deployment_name,
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
        ingress_backend = client.V1beta1IngressBackend(
            service_name=self.deployment_name,
            service_port=InteractiveDeploymentK8sBuilder.internal_service_port
        )
        ingress_rule_value = client.V1beta1HTTPIngressRuleValue([
            client.V1beta1HTTPIngressPath(
                path=self.path, backend=ingress_backend)])
        spec = client.V1beta1IngressSpec(
            rules=[client.V1beta1IngressRule(http=ingress_rule_value)])
        ingress = client.V1beta1Ingress(
            api_version="extensions/v1beta1",
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
            type='LoadBalancer',
            ports=[client.V1ServicePort(
                port=InteractiveDeploymentK8sBuilder.internal_service_port,
                target_port=self.port)],
            selector={"app": self.deployment_name})
        service = client.V1beta1APIService(
            api_version="v1",
            kind="Service",
            spec=spec,
            metadata=metadata,
        )
        return service

    def _build_deployment(self, metadata):
        """Build deployment Kubernetes object.

        :param metadata: Common Kubernetes metadata for the interactive
            deployment.
        """
        pod_spec = client.V1PodSpec(
            containers=[client.V1Container(name=self.deployment_name,
                                           image=self.image)])
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": self.deployment_name}),
            spec=pod_spec)
        spec = client.V1DeploymentSpec(
            selector=client.V1LabelSelector(
                match_labels={'app': self.deployment_name}),
            replicas=1,
            template=template)
        deployment = client.V1Deployment(
            api_version="extensions/v1beta1",
            kind="Deployment",
            metadata=metadata,
            spec=spec,
        )
        return deployment

    def add_command(self, command):
        """Add a command to the deployment."""
        self.kubernetes_objects["deployment"].spec.template.spec. \
            containers[0].command = command

    def add_command_arguments(self, args):
        """Add command line arguments in addition to the command."""
        self.kubernetes_objects["deployment"].spec.template.spec. \
            containers[0].args = args

    def get_deployment_objects(self):
        """Return the alrady built Kubernetes objects."""
        return self.kubernetes_objects


def build_interactive_jupyter_deployment_k8s_objects(
        deployment_name, access_path, access_token=None, image=None):
    """Build the Kubernetes specification for a Jupyter NB interactive session.

    :param workflow_run_name: The workflow run name will be used to tag
        all Kubernetes objects spawned for the given interactive session.
    :param access_path: URL path where the interactive session will be
        accessible. Note that this path should be set as base path of
        the interactive session service whenever redirections are needed,
        i.e. if we expose ``/1234`` and then application does a redirect to
        /me Traefik won't send the request to the interactive session
        (``/1234/me``) but to the root path (``/me``) giving most probably
        a ``404``.
    :param image: Jupyter Notebook image to use, i.e.
        ``jupyter/tensorflow-notebook`` to enable ``tensorflow``.
    """
    image = image or JUPYTER_INTERACTIVE_SESSION_DEFAULT_IMAGE
    port = JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT
    deployment_builder = InteractiveDeploymentK8sBuilder(deployment_name,
                                                         image, port,
                                                         access_path)
    deployment_builder.add_command(["start-notebook.sh"])
    command_args = [
        "--NotebookApp.base_url='{base_url}'".format(base_url=access_path)
    ]
    if access_token:
        command_args.append("--NotebookApp.token='{access_token}'".format(
            access_token=access_token
        ))
    deployment_builder.add_command_arguments(command_args)
    return deployment_builder.get_deployment_objects()


build_interactive_k8s_objects = {
    "jupyter": build_interactive_jupyter_deployment_k8s_objects
}
"""Build interactive k8s deployment objects."""


def instantiate_k8s_objects(kubernetes_objects, namespace):
    """Instantiate Kubernetes objects.

    :param kubernetes_objects: Dictionary composed by the object kind as
        key and the object itself as value.
    :param namespace: Kubernetes namespace where the objects will be deployed.
    """
    instantiate_k8s_object = {
        "deployment":
        current_k8s_extensions_v1beta1.create_namespaced_deployment,
        "service":
        current_k8s_corev1_api_client.create_namespaced_service,
        "ingress":
        current_k8s_extensions_v1beta1.create_namespaced_ingress
    }
    try:
        for obj in kubernetes_objects.items():
            kind = obj[0]
            k8s_object = obj[1]
            instantiate_k8s_object[kind](namespace, k8s_object)
    except KeyError:
        raise Exception("Unsupported Kubernetes object kind {}.".format(kind))
