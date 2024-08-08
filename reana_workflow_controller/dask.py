# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Dask resource manager."""
import logging
import os
import yaml

from flask import current_app

from reana_commons.config import (
    K8S_CERN_EOS_AVAILABLE,
    K8S_CERN_EOS_MOUNT_CONFIGURATION,
    KRB5_STATUS_FILE_LOCATION,
    REANA_JOB_HOSTPATH_MOUNTS,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_commons.k8s.api_client import (
    current_k8s_custom_objects_api_client,
)
from reana_commons.k8s.kerberos import get_kerberos_k8s_config
from reana_commons.k8s.secrets import UserSecretsStore
from reana_commons.k8s.volumes import (
    get_workspace_volume,
    get_reana_shared_volume,
)

from reana_workflow_controller.k8s import create_dask_dashboard_ingress


class DaskResourceManager:
    """Dask resource manager."""

    def __init__(
        self,
        cluster_name,
        workflow_spec,
        workflow_workspace,
        user_id,
        num_of_workers,
        single_worker_memory,
    ):
        """Instantiate Dask resource manager.

        :param cluster_name: Name of the cluster
        :type cluster_name: str
        :param workflow_spec: REANA workflow specification
        :type workflow_spec: dict
        :param workflow_workspace: Workflow workspace path
        :type workflow_workspace: str
        :param user_id: Id of the user
        :type user_id: str
        """
        self.cluster_name = cluster_name
        self.num_of_workers = num_of_workers
        self.single_worker_memory = single_worker_memory
        self.autoscaler_name = f"dask-autoscaler-{cluster_name}"
        self.workflow_spec = workflow_spec
        self.workflow_workspace = workflow_workspace
        self.workflow_id = workflow_workspace.split("/")[-1]
        self.user_id = user_id

        self.cluster_spec = workflow_spec.get("resources", {}).get("dask", [])
        self.cluster_body, self.autoscaler_body = self._load_dask_templates()
        self.cluster_image = self.cluster_spec["image"]
        self.dask_scheduler_uri = (
            f"{self.cluster_name}-scheduler.default.svc.cluster.local:8786"
        )

        self.secrets_store = UserSecretsStore.fetch(self.user_id)
        self.secret_env_vars = self.secrets_store.get_env_secrets_as_k8s_spec()
        self.secrets_volume_mount = (
            self.secrets_store.get_secrets_volume_mount_as_k8s_spec()
        )
        self.kubernetes_uid = WORKFLOW_RUNTIME_USER_UID

    def _load_dask_templates(self):
        """Load Dask templates from YAML files."""
        with open(
            "reana_workflow_controller/templates/dask_cluster.yaml", "r"
        ) as dask_cluster_yaml, open(
            "reana_workflow_controller/templates/dask_autoscaler.yaml", "r"
        ) as dask_autoscaler_yaml:
            dask_cluster_body = yaml.safe_load(dask_cluster_yaml)
            dask_autoscaler_body = yaml.safe_load(dask_autoscaler_yaml)
            dask_cluster_body["spec"]["worker"]["spec"]["initContainers"] = []
            dask_cluster_body["spec"]["worker"]["spec"]["containers"][0]["env"] = []
            dask_cluster_body["spec"]["worker"]["spec"]["containers"][0][
                "volumeMounts"
            ] = []
            dask_cluster_body["spec"]["worker"]["spec"]["volumes"] = []

            return dask_cluster_body, dask_autoscaler_body

    def create_dask_resources(self):
        """Create necessary Dask resources for the workflow."""
        self._prepare_cluster()
        self._create_dask_cluster()
        self._create_dask_autoscaler()
        create_dask_dashboard_ingress(self.cluster_name, self.workflow_id)

    def _prepare_cluster(self):
        """Prepare Dask cluster body by adding necessary image-pull secrets, volumes, volume mounts, init containers and sidecar containers."""
        self._add_image_pull_secrets()
        self._add_hostpath_volumes()
        self._add_workspace_volume()
        self._add_shared_volume()
        self._add_eos_volume()

        # Add the name of the cluster, used in scheduler service name
        self.cluster_body["metadata"] = {"name": self.cluster_name}

        # Add the name of the dask autoscaler
        self.autoscaler_body["metadata"] = {"name": self.autoscaler_name}

        self.cluster_body["spec"]["scheduler"]["service"]["selector"][
            "dask.org/cluster-name"
        ] = self.cluster_name

        # Connect autoscaler to the cluster
        self.autoscaler_body["spec"]["cluster"] = self.cluster_name

        # Add image to worker and scheduler
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
            "image"
        ] = self.cluster_image
        self.cluster_body["spec"]["scheduler"]["spec"]["containers"][0][
            "image"
        ] = self.cluster_image

        # Create the worker command
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["args"][
            0
        ] = f'cd {self.workflow_workspace} && {self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["args"][0]}'

        # Set resource limits for workers
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["resources"] = {
            "limits": {"memory": f"{self.single_worker_memory}", "cpu": "1"}
        }

        # Set max limit on autoscaler
        self.autoscaler_body["spec"]["maximum"] = self.num_of_workers

        # Add DASK SCHEDULER URI env variable
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["env"].append(
            {"name": "DASK_SCHEDULER_URI", "value": self.dask_scheduler_uri},
        )

        # Add secrets
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["env"].extend(
            self.secret_env_vars
        )

        self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
            "volumeMounts"
        ].append(self.secrets_volume_mount)

        self.cluster_body["spec"]["worker"]["spec"]["volumes"].append(
            self.secrets_store.get_file_secrets_volume_as_k8s_specs()
        )

        # FIXME: Decide how to detect if krb5, rucio and voms_proxy are needed
        kerberos = False
        rucio = False
        voms_proxy = False

        if kerberos:
            self._add_krb5_containers()
        if voms_proxy:
            self._add_voms_proxy_init_container()
        if rucio:
            self._add_rucio_init_container()

    def _add_image_pull_secrets(self):
        """Attach the configured image pull secrets to scheduler and worker containers."""
        image_pull_secrets = []
        for secret_name in current_app.config["IMAGE_PULL_SECRETS"]:
            if secret_name:
                image_pull_secrets.append({"name": secret_name})

        self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
            "imagePullSecrets"
        ] = image_pull_secrets

        self.cluster_body["spec"]["scheduler"]["spec"]["containers"][0][
            "imagePullSecrets"
        ] = image_pull_secrets

    def _add_workspace_volume(self):
        """Add workspace volume to Dask workers."""
        volume_mount, volume = get_workspace_volume(self.workflow_workspace)
        self._add_volumes([(volume_mount, volume)])

    def _add_eos_volume(self):
        """Add EOS volume to Dask cluster body."""
        if K8S_CERN_EOS_AVAILABLE:
            self._add_volumes(
                [
                    (
                        K8S_CERN_EOS_MOUNT_CONFIGURATION["volumeMounts"],
                        K8S_CERN_EOS_MOUNT_CONFIGURATION["volume"],
                    )
                ]
            )

    def _add_shared_volume(self):
        """Add shared CephFS volume to Dask workers."""
        shared_volume = get_reana_shared_volume()

        if not any(
            v["name"] == shared_volume["name"]
            for v in self.cluster_body["spec"]["worker"]["spec"]["volumes"]
        ):
            self.cluster_body["spec"]["worker"]["spec"]["volumes"].append(shared_volume)

    def _add_hostpath_volumes(self):
        """Add hostPath mounts from configuration to the Dask workers."""
        volumes_to_mount = []
        for mount in REANA_JOB_HOSTPATH_MOUNTS:
            volume_mount = {
                "name": mount["name"],
                "mountPath": mount.get("mountPath", mount["hostPath"]),
            }
            volume = {"name": mount["name"], "hostPath": {"path": mount["hostPath"]}}
            volumes_to_mount.append((volume_mount, volume))

        self._add_volumes(volumes_to_mount)

    def _add_volumes(self, volumes):
        """Add provided volumes to Dask cluster body."""
        for volume_mount, volume in volumes:
            self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
                "volumeMounts"
            ].append(volume_mount)
            self.cluster_body["spec"]["worker"]["spec"]["volumes"].append(volume)

    def _add_krb5_containers(self):
        """Add krb5 init and renew containers for Dask workers."""
        krb5_config = get_kerberos_k8s_config(
            self.secrets_store,
            kubernetes_uid=self.kubernetes_uid,
        )

        self.cluster_body["spec"]["worker"]["spec"]["volumes"].extend(
            krb5_config.volumes
        )
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
            "volumeMounts"
        ].extend(krb5_config.volume_mounts)
        # Add the Kerberos token cache file location to the job container
        # so every instance of Kerberos picks it up even if it doesn't read
        # the configuration file.
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["env"].extend(
            krb5_config.env
        )
        # Add Kerberos init container used to generate ticket
        self.cluster_body["spec"]["worker"]["spec"]["initContainers"].append(
            krb5_config.init_container
        )

        # Add Kerberos renew container to renew ticket periodically for long-running jobs
        self.cluster_body["spec"]["worker"]["spec"]["containers"].append(
            krb5_config.renew_container
        )

        # Extend the main job command to create a file after it's finished
        existing_args = self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
            "args"
        ]

        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["args"] = [
            f"trap 'touch {KRB5_STATUS_FILE_LOCATION}' EXIT; " + existing_args[0]
        ]

    def _add_voms_proxy_init_container(self):
        """Add sidecar container for Dask workers."""
        ticket_cache_volume = {"name": "voms-proxy-cache", "emptyDir": {}}
        volume_mounts = [
            {
                "name": ticket_cache_volume["name"],
                "mountPath": current_app.config["VOMSPROXY_CERT_CACHE_LOCATION"],
            }
        ]

        voms_proxy_file_path = os.path.join(
            current_app.config["VOMSPROXY_CERT_CACHE_LOCATION"],
            current_app.config["VOMSPROXY_CERT_CACHE_FILENAME"],
        )

        voms_proxy_vo = os.environ.get("VONAME", "")
        voms_proxy_user_file = os.environ.get("VOMSPROXY_FILE", "")

        if voms_proxy_user_file:
            # multi-user deployment mode, where we rely on VOMS proxy file supplied by the user
            voms_proxy_container = {
                "image": current_app.config["VOMSPROXY_CONTAINER_IMAGE"],
                "command": ["/bin/bash"],
                "args": [
                    "-c",
                    'if [ ! -f "/etc/reana/secrets/{voms_proxy_user_file}" ]; then \
                        echo "[ERROR] VOMSPROXY_FILE {voms_proxy_user_file} does not exist in user secrets."; \
                        exit; \
                     fi; \
                     cp /etc/reana/secrets/{voms_proxy_user_file} {voms_proxy_file_path}; \
                     chown {kubernetes_uid} {voms_proxy_file_path}'.format(
                        voms_proxy_user_file=voms_proxy_user_file,
                        voms_proxy_file_path=voms_proxy_file_path,
                        kubernetes_uid=self.kubernetes_uid,
                    ),
                ],
                "name": current_app.config["VOMSPROXY_CONTAINER_NAME"],
                "imagePullPolicy": "IfNotPresent",
                "volumeMounts": [self.secrets_volume_mount] + volume_mounts,
                "env": self.secret_env_vars,
            }
        else:
            # single-user deployment mode, where we generate VOMS proxy file in the sidecar from user secrets
            voms_proxy_container = {
                "image": current_app.config["VOMSPROXY_CONTAINER_IMAGE"],
                "command": ["/bin/bash"],
                "args": [
                    "-c",
                    'if [ ! -f "/etc/reana/secrets/userkey.pem" ]; then \
                        echo "[ERROR] File userkey.pem does not exist in user secrets."; \
                        exit; \
                     fi; \
                     if [ ! -f "/etc/reana/secrets/usercert.pem" ]; then \
                        echo "[ERROR] File usercert.pem does not exist in user secrets."; \
                        exit; \
                     fi; \
                     if [ -z "$VOMSPROXY_PASS" ]; then \
                        echo "[ERROR] Environment variable VOMSPROXY_PASS is not set in user secrets."; \
                        exit; \
                     fi; \
                     if [ -z "$VONAME" ]; then \
                        echo "[ERROR] Environment variable VONAME is not set in user secrets."; \
                        exit; \
                     fi; \
                     cp /etc/reana/secrets/userkey.pem /tmp/userkey.pem; \
                         chmod 400 /tmp/userkey.pem; \
                         echo $VOMSPROXY_PASS | base64 -d | voms-proxy-init \
                         --voms {voms_proxy_vo} --key /tmp/userkey.pem \
                         --cert $(readlink -f /etc/reana/secrets/usercert.pem) \
                         --pwstdin --out {voms_proxy_file_path}; \
                         chown {kubernetes_uid} {voms_proxy_file_path}'.format(
                        voms_proxy_vo=voms_proxy_vo.lower(),
                        voms_proxy_file_path=voms_proxy_file_path,
                        kubernetes_uid=self.kubernetes_uid,
                    ),
                ],
                "name": current_app.config["VOMSPROXY_CONTAINER_NAME"],
                "imagePullPolicy": "IfNotPresent",
                "volumeMounts": [self.secrets_volume_mount] + volume_mounts,
                "env": self.secret_env_vars,
            }

        self.cluster_body["spec"]["worker"]["spec"]["volumes"].extend(
            [ticket_cache_volume]
        )
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
            "volumeMounts"
        ].extend(volume_mounts)

        # XrootD will look for a valid grid proxy in the location pointed to
        # by the environment variable $X509_USER_PROXY
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["env"].append(
            {"name": "X509_USER_PROXY", "value": voms_proxy_file_path}
        )

        self.cluster_body["spec"]["worker"]["spec"]["initContainers"].append(
            voms_proxy_container
        )

    def _add_rucio_init_container(self):
        """Add sidecar container for Dask workers."""
        ticket_cache_volume = {"name": "rucio-cache", "emptyDir": {}}
        volume_mounts = [
            {
                "name": ticket_cache_volume["name"],
                "mountPath": current_app.config["RUCIO_CACHE_LOCATION"],
            }
        ]

        rucio_config_file_path = os.path.join(
            current_app.config["RUCIO_CACHE_LOCATION"],
            current_app.config["RUCIO_CFG_CACHE_FILENAME"],
        )

        cern_bundle_path = os.path.join(
            current_app.config["RUCIO_CACHE_LOCATION"],
            current_app.config["RUCIO_CERN_BUNDLE_CACHE_FILENAME"],
        )

        rucio_account = os.environ.get("RUCIO_USERNAME", "")
        voms_proxy_vo = os.environ.get("VONAME", "")

        # Detect Rucio hosts from VO names
        if voms_proxy_vo == "atlas":
            rucio_host = "https://voatlasrucio-server-prod.cern.ch"
            rucio_auth_host = "https://voatlasrucio-auth-prod.cern.ch"
        else:
            rucio_host = f"https://{voms_proxy_vo}-rucio.cern.ch"
            rucio_auth_host = f"https://{voms_proxy_vo}-rucio-auth.cern.ch"

        # Allow overriding detected Rucio hosts by user-provided environment variables
        rucio_host = os.environ.get("RUCIO_RUCIO_HOST", rucio_host)
        rucio_auth_host = os.environ.get("RUCIO_AUTH_HOST", rucio_auth_host)

        rucio_config_container = {
            "image": current_app.config["RUCIO_CONTAINER_IMAGE"],
            "command": ["/bin/bash"],
            "args": [
                "-c",
                'if [ -z "$VONAME" ]; then \
                    echo "[ERROR] Environment variable VONAME is not set in user secrets."; \
                    exit; \
                 fi; \
                 if [ -z "$RUCIO_USERNAME" ]; then \
                    echo "[ERROR] Environment variable RUCIO_USERNAME is not set in user secrets."; \
                    exit; \
                 fi; \
                 export RUCIO_CFG_ACCOUNT={rucio_account} \
                    RUCIO_CFG_CLIENT_VO={voms_proxy_vo} \
                    RUCIO_CFG_RUCIO_HOST={rucio_host} \
                    RUCIO_CFG_AUTH_HOST={rucio_auth_host}; \
                cp /etc/pki/tls/certs/CERN-bundle.pem {cern_bundle_path}; \
                j2 /opt/user/rucio.cfg.j2 > {rucio_config_file_path}'.format(
                    rucio_host=rucio_host,
                    rucio_auth_host=rucio_auth_host,
                    rucio_account=rucio_account,
                    voms_proxy_vo=voms_proxy_vo,
                    cern_bundle_path=cern_bundle_path,
                    rucio_config_file_path=rucio_config_file_path,
                ),
            ],
            "name": current_app.config["RUCIO_CONTAINER_NAME"],
            "imagePullPolicy": "IfNotPresent",
            "volumeMounts": [self.secrets_volume_mount] + volume_mounts,
            "env": self.secret_env_vars,
        }

        self.cluster_body["spec"]["worker"]["spec"]["volumes"].extend(
            [ticket_cache_volume]
        )
        self.cluster_body["spec"]["worker"]["spec"]["containers"][0][
            "volumeMounts"
        ].extend(volume_mounts)

        self.cluster_body["spec"]["worker"]["spec"]["containers"][0]["env"].append(
            {"name": "RUCIO_CONFIG", "value": rucio_config_file_path}
        )

        self.cluster_body["spec"]["worker"]["spec"]["initContainers"].append(
            rucio_config_container
        )

    def _create_dask_cluster(self):
        """Create Dask cluster resource."""
        try:
            current_k8s_custom_objects_api_client.create_namespaced_custom_object(
                group="kubernetes.dask.org",
                version="v1",
                plural="daskclusters",
                namespace="default",
                body=self.cluster_body,
            )
        except Exception:
            logging.exception(
                "An error occurred while trying to create a Dask cluster."
            )
            raise

    def _create_dask_autoscaler(self):
        """Create Dask autoscaler resource."""
        try:
            current_k8s_custom_objects_api_client.create_namespaced_custom_object(
                group="kubernetes.dask.org",
                version="v1",
                plural="daskautoscalers",
                namespace="default",
                body=self.autoscaler_body,
            )
        except Exception:
            logging.exception(
                "An error occurred while trying to create a Dask autoscaler."
            )
            raise


def requires_dask(workflow):
    """Check whether Dask is necessary to run the workflow."""
    return bool(
        workflow.reana_specification["workflow"].get("resources", {}).get("dask", False)
    )
