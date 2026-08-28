# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2024, 2025 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller Kubernetes utils."""

import logging

from kubernetes import client
from kubernetes.client.rest import ApiException
from reana_commons.config import (
    K8S_USE_SECURITY_CONTEXT,
    REANA_WORKFLOW_UMASK,
    REANA_RUNTIME_SESSIONS_KUBERNETES_NODE_LABEL,
    REANA_RUNTIME_KUBERNETES_NAMESPACE,
    WORKFLOW_RUNTIME_USER_GID,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_commons.k8s.api_client import (
    current_k8s_appsv1_api_client,
    current_k8s_corev1_api_client,
    current_k8s_networking_api_client,
)
from reana_commons.k8s.kerberos import get_kerberos_k8s_config
from reana_commons.k8s.secrets import UserSecretsStore
from reana_commons.k8s.volumes import (
    get_k8s_cvmfs_volumes,
    get_workspace_volume,
)

from reana_workflow_controller.config import (  # isort:skip
    JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT,
    REANA_INGRESS_ANNOTATIONS,
    REANA_INGRESS_CLASS_NAME,
    REANA_INGRESS_HOST,
    REANA_RUNTIME_FS_GROUP_CHANGE_POLICY,
    REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS,
)
from reana_workflow_controller.errors import (
    REANAInteractiveSessionError,
    ReservedEnvironmentVariableError,
)

LOGGER = logging.getLogger(__name__)

RESERVED_SESSION_ENV_VARS = {
    "NOTEBOOK_ARGS",
    "NB_GID",
    "NB_UMASK",
    "REANA_WORKSPACE",
}
"""Interactive-session environment variables owned by the controller.

``NOTEBOOK_ARGS`` carries the per-session notebook token, so a user value must
never win: Kubernetes resolves duplicate names to the last entry, and user
secrets are appended after the managed ones.
"""


def _filter_reserved_session_env_var_collisions(env_vars):
    """Reject user env secrets that collide with controller-managed variables.

    Silently dropping a colliding secret is invisible to both the user and
    the admin: the REST response reports success either way, so a user whose
    secret happens to be named e.g. ``REANA_WORKSPACE`` would have it
    permanently and silently excluded from every interactive session with no
    signal to notice, let alone fix, the collision.
    """
    colliding_names = sorted(
        env_var["name"]
        for env_var in env_vars
        if env_var["name"] in RESERVED_SESSION_ENV_VARS
    )
    if colliding_names:
        raise ReservedEnvironmentVariableError(
            "Cannot start interactive session: secret name(s) "
            f"{', '.join(colliding_names)} are reserved for REANA-managed "
            "interactive-session configuration. Please rename the "
            "conflicting secret(s) and try again."
        )
    return env_vars


def _restricted_session_pod_security_context() -> client.V1PodSecurityContext | None:
    """Return the pod security context for interactive sessions."""
    if not K8S_USE_SECURITY_CONTEXT:
        return None
    pod_security_context_kwargs = dict(
        fs_group=int(WORKFLOW_RUNTIME_USER_GID),
        fs_group_change_policy=REANA_RUNTIME_FS_GROUP_CHANGE_POLICY,
    )
    if REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS:
        pod_security_context_kwargs["supplemental_groups"] = (
            REANA_RUNTIME_SESSIONS_SUPPLEMENTAL_GROUPS
        )
    return client.V1PodSecurityContext(**pod_security_context_kwargs)


def _restricted_session_container_security_context() -> client.V1SecurityContext | None:
    """Return the container security context for interactive sessions."""
    if not K8S_USE_SECURITY_CONTEXT:
        return None
    return client.V1SecurityContext(
        run_as_group=int(WORKFLOW_RUNTIME_USER_GID),
        run_as_user=int(WORKFLOW_RUNTIME_USER_UID),
        run_as_non_root=True,
        allow_privilege_escalation=False,
        capabilities=client.V1Capabilities(drop=["ALL"]),
        seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
    )


def _restricted_kerberos_container_security_context(kubernetes_uid: int) -> dict:
    """Return the expected PSA-restricted security context for Kerberos containers."""
    return {
        "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
        "runAsUser": int(kubernetes_uid),
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }


def _normalize_kerberos_container_security_context(
    kerberos_config, kubernetes_uid: int
):
    """Backfill missing Kerberos security-context fields from older commons releases."""
    if not K8S_USE_SECURITY_CONTEXT:
        return kerberos_config

    for container_name in ("init_container", "renew_container"):
        container = getattr(kerberos_config, container_name, None)
        if not container:
            continue

        expected_security_context = _restricted_kerberos_container_security_context(
            kubernetes_uid
        )
        if "securityContext" not in container:
            container["securityContext"] = expected_security_context
            continue

        for field, value in expected_security_context.items():
            if field not in container["securityContext"]:
                container["securityContext"][field] = value

    return kerberos_config


def get_compatible_kerberos_k8s_config(user_secrets, kubernetes_uid: int):
    """Return Kerberos k8s config across released and unreleased commons APIs."""
    try:
        kerberos_config = get_kerberos_k8s_config(
            user_secrets,
            kubernetes_uid=kubernetes_uid,
            use_security_context=K8S_USE_SECURITY_CONTEXT,
        )
    except TypeError as exc:
        if "unexpected keyword argument 'use_security_context'" not in str(exc):
            raise
        kerberos_config = get_kerberos_k8s_config(
            user_secrets,
            kubernetes_uid=kubernetes_uid,
        )
    return _normalize_kerberos_container_security_context(
        kerberos_config,
        kubernetes_uid,
    )


class InteractiveDeploymentK8sBuilder(object):
    """Build Kubernetes deployment objects for interactive sessions."""

    internal_service_port = 8081
    """Port exposed by the Service placed in front of the Deployment and
       referenced by the Ingress. This port has nothing to do with the
       port exposed by deployment itself, the one which can change
       from one interactive session application to other."""

    def __init__(
        self,
        deployment_name,
        workflow_id,
        owner_id,
        workspace,
        image,
        port,
        path,
        cvmfs_repos=None,
    ):
        """Initialise basic interactive deployment builder for Kubernetes.

        :param deployment_name: Name which identifies all deployment objects
            and maps to the workflow it belongs.
        :param workflow_id: UUID of the workflow to which the interactive
            session belongs to.
        :param owner_id: Owner of the interactive session.
        :param workspace: Path to the interactive session workspace, which
            matches with the workflow workspace the interactive session
            belongs to.
        :param image: Docker image which the deployment will use as base.
        :param port: Port exposed by the Docker image.
        :param path: Path where the interactive session will be accessible
            from outside the cluster.
        """
        self.deployment_name = deployment_name
        self.workflow_id = workflow_id
        self.owner_id = owner_id
        self.workspace = workspace
        self.image = image
        self.port = port
        self.path = path
        self.cvmfs_repos = cvmfs_repos or []
        metadata = client.V1ObjectMeta(
            name=deployment_name,
            labels={"reana_workflow_mode": "session"},
        )
        self._session_container = client.V1Container(
            name=self.deployment_name, image=self.image, env=[], volume_mounts=[]
        )
        self._pod_spec = client.V1PodSpec(
            containers=[self._session_container],
            volumes=[],
            node_selector=REANA_RUNTIME_SESSIONS_KUBERNETES_NODE_LABEL,
            # Disable service discovery with env variables, so that the environment is
            # not polluted with variables like `REANA_SERVER_SERVICE_HOST`
            enable_service_links=False,
            automount_service_account_token=False,
            security_context=_restricted_session_pod_security_context(),
        )

        self.kubernetes_objects = {
            "ingress": self._build_ingress(),
            "service": self._build_service(metadata),
            "deployment": self._build_deployment(metadata),
        }

    def _build_ingress(self):
        """Build ingress Kubernetes object.

        :param metadata: Common Kubernetes metadata for the interactive
            deployment.
        """
        ingress_service_backend = client.V1IngressServiceBackend(
            name=self.deployment_name,
            port=client.V1ServiceBackendPort(
                number=InteractiveDeploymentK8sBuilder.internal_service_port
            ),
        )
        ingress_backend = client.V1IngressBackend(service=ingress_service_backend)
        ingress_rule_value = client.V1HTTPIngressRuleValue(
            [
                client.V1HTTPIngressPath(
                    path=self.path, backend=ingress_backend, path_type="Prefix"
                )
            ]
        )
        spec = client.V1IngressSpec(
            rules=[
                client.V1IngressRule(http=ingress_rule_value, host=REANA_INGRESS_HOST)
            ]
        )
        if REANA_INGRESS_CLASS_NAME:
            spec.ingress_class_name = REANA_INGRESS_CLASS_NAME
        ingress = client.V1Ingress(
            api_version="networking.k8s.io/v1",
            kind="Ingress",
            spec=spec,
            metadata=client.V1ObjectMeta(
                name=self.deployment_name,
                annotations=REANA_INGRESS_ANNOTATIONS,
            ),
        )
        return ingress

    def _build_service(self, metadata):
        """Build service Kubernetes object.

        :param metadata: Common Kubernetes metadata for the interactive
            deployment.
        """
        spec = client.V1ServiceSpec(
            type="ClusterIP",
            ports=[
                client.V1ServicePort(
                    port=InteractiveDeploymentK8sBuilder.internal_service_port,
                    target_port=self.port,
                )
            ],
            selector={"app": self.deployment_name},
        )
        service = client.V1APIService(
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
        labels = {
            "app": self.deployment_name,
            "reana_workflow_mode": "session",
            "reana-run-session-workflow-uuid": str(self.workflow_id),
            "user-uuid": str(self.owner_id),
        }
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=labels),
            spec=self._pod_spec,
        )
        spec = client.V1DeploymentSpec(
            selector=client.V1LabelSelector(match_labels=labels),
            replicas=1,
            template=template,
        )
        deployment = client.V1Deployment(
            api_version="apps/v1",
            kind="Deployment",
            metadata=metadata,
            spec=spec,
        )

        return deployment

    def add_command(self, command):
        """Add a command to the deployment."""
        self._session_container.command = command

    def add_command_arguments(self, args):
        """Add command line arguments in addition to the command."""
        self._session_container.args = args

    def add_reana_shared_storage(self):
        """Add the REANA shared file system volume mount to the deployment."""
        volume_mount, volume = get_workspace_volume(self.workspace)
        self._session_container.volume_mounts.append(volume_mount)
        self._pod_spec.volumes.append(volume)

    def add_cvmfs_repo_mounts(self, cvmfs_repos):
        """Add mounts for the provided CVMFS repositories to the deployment.

        :param cvmfs_mounts: List of CVMFS repos to make available.
        """
        cvmfs_volume_mounts, cvmfs_volumes = get_k8s_cvmfs_volumes(cvmfs_repos)
        self._pod_spec.volumes.extend(cvmfs_volumes)
        self._session_container.volume_mounts.extend(cvmfs_volume_mounts)

    def add_environment_variable(self, name, value):
        """Add an environment variable.

        :param name: Environment variable name.
        :param value: Environment variable value.
        """
        env_var = client.V1EnvVar(name, str(value))
        self._session_container.env.append(env_var)

    def add_secret_environment_variable(self, name, secret_name, secret_key):
        """Add an environment variable sourced from a Kubernetes Secret."""
        self._session_container.env.append(
            client.V1EnvVar(
                name=name,
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name=secret_name,
                        key=secret_key,
                    )
                ),
            )
        )

    def add_session_secret(self, session_secret):
        """Expose a notebook token through a per-session Kubernetes Secret."""
        secret_name = "{}-auth".format(self.deployment_name)
        secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(
                name=secret_name,
                labels={
                    "reana_workflow_mode": "session",
                    "reana-run-session-workflow-uuid": str(self.workflow_id),
                    "user-uuid": str(self.owner_id),
                },
            ),
            # Jupyter Docker Stacks' start-notebook.py reads NOTEBOOK_ARGS and
            # shlex-splits it before starting Jupyter. Keeping the complete
            # argument in the Secret avoids materialising the token in the Pod
            # or Deployment specification.
            string_data={
                "notebook_args": "--NotebookApp.token={}".format(session_secret)
            },
            type="Opaque",
        )
        # Keep the Ingress first: instantiate_chained_k8s_objects uses the
        # first object as the owner root and session shutdown deletes it to
        # cascade cleanup.  The Secret can still be created before the
        # Deployment while retaining that ownership chain.
        objects = {"ingress": self.kubernetes_objects["ingress"], "secret": secret}
        objects.update(
            (name, value)
            for name, value in self.kubernetes_objects.items()
            if name != "ingress"
        )
        self.kubernetes_objects = objects
        self.add_secret_environment_variable(
            "NOTEBOOK_ARGS", secret_name, "notebook_args"
        )

    def add_run_with_runtime_user_permissions(self):
        """Run interactive session with the default non-root REANA user."""
        self._session_container.security_context = (
            _restricted_session_container_security_context()
        )

    def add_user_secrets(self):
        """Mount the "file" secrets and set the "env" secrets in the container."""
        user_secrets = UserSecretsStore.fetch(self.owner_id)
        environment_secrets = _filter_reserved_session_env_var_collisions(
            user_secrets.get_env_secrets_as_k8s_spec()
        )

        # mount file secrets
        secrets_volume = user_secrets.get_file_secrets_volume_as_k8s_specs()
        secrets_volume_mount = user_secrets.get_secrets_volume_mount_as_k8s_spec()
        self._pod_spec.volumes.append(secrets_volume)
        self._session_container.volume_mounts.append(secrets_volume_mount)

        # set environment secrets
        self._session_container.env += environment_secrets

    def get_deployment_objects(self):
        """Return the alrady built Kubernetes objects."""
        return self.kubernetes_objects


def build_interactive_jupyter_deployment_k8s_objects(
    deployment_name,
    workspace,
    access_path,
    image,
    session_secret,
    cvmfs_repos=None,
    owner_id=None,
    workflow_id=None,
    expose_secrets=True,
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
    :param image: Jupyter Notebook image to use, i.e.
        ``jupyter/tensorflow-notebook`` to enable ``tensorflow``.
    :param session_secret: Random per-session secret used as the notebook
        access token (never a user credential).
    :param cvmfs_mounts: List of CVMFS repos to make available.
    :param owner_id: Owner of the interactive session.
    :param workflow_id: UUID of the workflow to which the interactive
        session belongs to.
    :param expose_secrets: If true, mount the "file" secrets and set the
        "env" secrets in jupyter's pod.
    """
    if not session_secret:
        raise ValueError("An interactive session secret is required.")
    cvmfs_repos = cvmfs_repos or []
    port = JUPYTER_INTERACTIVE_SESSION_DEFAULT_PORT
    deployment_builder = InteractiveDeploymentK8sBuilder(
        deployment_name, workflow_id, owner_id, workspace, image, port, access_path
    )
    command_args = [
        "start-notebook.sh",
        "--NotebookApp.base_url='{base_url}'".format(base_url=access_path),
        "--notebook-dir='{workflow_workspace}'".format(workflow_workspace=workspace),
        f'--NotebookApp.terminado_settings={{"shell_command": ["/usr/bin/bash", "-c", "cd \'{workspace}\' && bash"]}}',
    ]
    deployment_builder.add_command_arguments(command_args)
    deployment_builder.add_session_secret(session_secret)
    deployment_builder.add_reana_shared_storage()
    if cvmfs_repos:
        deployment_builder.add_cvmfs_repo_mounts(cvmfs_repos)
    if expose_secrets:
        deployment_builder.add_user_secrets()
    deployment_builder.add_environment_variable("NB_GID", 0)
    # Changes umask so all files generated by the Jupyter Notebook can be
    # modified by the root group users.
    deployment_builder.add_environment_variable("NB_UMASK", REANA_WORKFLOW_UMASK)
    deployment_builder.add_environment_variable("REANA_WORKSPACE", workspace)
    deployment_builder.add_run_with_runtime_user_permissions()
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
        "secret": current_k8s_corev1_api_client.create_namespaced_secret,
        "deployment": current_k8s_appsv1_api_client.create_namespaced_deployment,
        "service": current_k8s_corev1_api_client.create_namespaced_service,
        "ingress": current_k8s_networking_api_client.create_namespaced_ingress,
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
            f"create_namespaced_deployment_rollback: {e}\n"
        )


def delete_k8s_objects_if_exist(kubernetes_objects, namespace):
    """Delete Kubernetes objects if they exist.

    :param kubernetes_objects: Dictionary composed by the object kind as
        key and the object itself as value.
    :param namespace: Kubernetes namespace where the objects will be deleted
        from.
    """
    delete_k8s_object = {
        "secret": current_k8s_corev1_api_client.delete_namespaced_secret,
        "deployment": current_k8s_appsv1_api_client.delete_namespaced_deployment,
        "service": current_k8s_corev1_api_client.delete_namespaced_service,
        "ingress": current_k8s_networking_api_client.delete_namespaced_ingress,
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
        current_k8s_networking_api_client.delete_namespaced_ingress(
            name=ingress_name, namespace=namespace, body=client.V1DeleteOptions()
        )
    except ApiException as k8s_api_exception:
        if k8s_api_exception.reason == "Not Found":
            raise Exception("K8s object was not found {}.".format(ingress_name))
        raise Exception(
            "Exception when calling ExtensionsV1beta1->"
            "Api->delete_namespaced_ingress: {}\n".format(k8s_api_exception)
        )


def check_pod_readiness_by_prefix(
    pod_name_prefix, namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE
):
    """Check the readiness of a Pod in the given namespace whose name starts with the specified prefix. We assume that there exists 0 or 1 pod with a given prefix."""
    try:
        pods = current_k8s_corev1_api_client.list_namespaced_pod(namespace=namespace)

        for pod in pods.items:
            if pod.metadata.name.startswith(pod_name_prefix):
                # Check the pod's readiness condition
                if pod.status.conditions:
                    for condition in pod.status.conditions:
                        if condition.type == "Ready":
                            return (
                                "Ready" if condition.status == "True" else "Not Ready"
                            )
                return "Not Ready"
        return "Not Found"
    except ApiException as e:
        return f"Error: {e.reason}"


def check_pod_status_by_prefix(
    pod_name_prefix, namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE
):
    """Check the pod status of a Pod in the given namespace whose name starts with the specified prefix. We assume that there exists 0 or 1 pod with a given prefix."""
    try:
        pods = current_k8s_corev1_api_client.list_namespaced_pod(namespace=namespace)

        for pod in pods.items:
            if pod.metadata.name.startswith(pod_name_prefix):
                return pod.status.phase
        return "Not Found"
    except ApiException as e:
        return f"Error: {e.reason}"
