# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2024, 2025 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Workflow run manager interface."""
import base64
import copy
import json
import logging
import os
from typing import List, Optional

from flask import current_app
from kubernetes import client
from kubernetes.client.models.v1_delete_options import V1DeleteOptions
from kubernetes.client.rest import ApiException
from reana_commons.config import (
    K8S_CERN_EOS_AVAILABLE,
    REANA_COMPONENT_NAMING_SCHEME,
    REANA_COMPONENT_PREFIX,
    REANA_INFRASTRUCTURE_KUBERNETES_NAMESPACE,
    REANA_JOB_HOSTPATH_MOUNTS,
    REANA_JOB_CONTROLLER_CONNECTION_CHECK_SLEEP,
    REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES,
    REANA_RUNTIME_KUBERNETES_NAMESPACE,
    REANA_RUNTIME_BATCH_KUBERNETES_NODE_LABEL,
    REANA_RUNTIME_JOBS_KUBERNETES_NODE_LABEL,
    REANA_RUNTIME_KUBERNETES_SERVICEACCOUNT_NAME,
    REANA_STORAGE_BACKEND,
    WORKFLOW_RUNTIME_GROUP_NAME,
    WORKFLOW_RUNTIME_USER_GID,
    WORKFLOW_RUNTIME_USER_NAME,
    WORKFLOW_RUNTIME_USER_UID,
    WORKSPACE_PATHS,
)
from reana_commons.k8s.api_client import current_k8s_batchv1_api_client
from reana_commons.k8s.kerberos import get_kerberos_k8s_config
from reana_commons.k8s.secrets import UserSecretsStore
from reana_commons.k8s.volumes import (
    create_cvmfs_persistent_volume_claim,
    get_workspace_volume,
)
from reana_commons.utils import (
    build_unique_component_name,
    format_cmd,
    get_dask_component_name,
)
from reana_db.config import SQLALCHEMY_DATABASE_URI
from reana_db.database import Session
from reana_db.models import Job, JobStatus, InteractiveSession, InteractiveSessionType

from reana_workflow_controller.errors import REANAInteractiveSessionError

from reana_workflow_controller.dask import (
    DaskResourceManager,
    requires_dask,
)

from reana_workflow_controller.k8s import (
    build_interactive_k8s_objects,
    delete_k8s_ingress_object,
    delete_k8s_objects_if_exist,
    instantiate_chained_k8s_objects,
)

from reana_workflow_controller.config import (  # isort:skip
    CONTAINER_IMAGE_ALIAS_PREFIXES,
    IMAGE_PULL_SECRETS,
    JOB_CONTROLLER_CONTAINER_PORT,
    JOB_CONTROLLER_ENV_VARS,
    JOB_CONTROLLER_SHUTDOWN_ENDPOINT,
    REANA_INTERACTIVE_SESSIONS_DEFAULT_IMAGES,
    REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS,
    REANA_INTERACTIVE_SESSIONS_RECOMMENDED_IMAGES,
    REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD,
    REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT,
    REANA_KUBERNETES_JOBS_MEMORY_LIMIT,
    REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT,
    REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT,
    REANA_WORKFLOW_ENGINE_IMAGE_CWL,
    REANA_WORKFLOW_ENGINE_IMAGE_SERIAL,
    REANA_WORKFLOW_ENGINE_IMAGE_SNAKEMAKE,
    REANA_WORKFLOW_ENGINE_IMAGE_YADAGE,
    WORKFLOW_ENGINE_COMMON_ENV_VARS,
    DEBUG_ENV_VARS,
    WORKFLOW_ENGINE_CWL_ENV_VARS,
    WORKFLOW_ENGINE_SERIAL_ENV_VARS,
    WORKFLOW_ENGINE_SNAKEMAKE_ENV_VARS,
    WORKFLOW_ENGINE_YADAGE_ENV_VARS,
    REANA_DASK_CLUSTER_DEFAULT_NUMBER_OF_WORKERS,
    REANA_DASK_CLUSTER_DEFAULT_SINGLE_WORKER_MEMORY,
)


def _container_image_aliases(
    image: str, prefixes=CONTAINER_IMAGE_ALIAS_PREFIXES
) -> List[str]:
    """Return possible aliases for a docker image reference.

    Aliases are obtained by adding/removing default prefixes like "docker.io/".
    Some of the returned aliases might not be valid docker image references,
    in particular when adding default prefixes to references that are already
    fully qualified.

    Example: the returned aliases for `docker.io/library/ubuntu:24.04` are:
      - `docker.io/library/ubuntu:24.04`
      - `library/ubuntu:24.04`
      - `ubuntu:24.04`
      - `library/docker.io/library/ubuntu:24.04` (not valid)
    """
    aliases = [image]
    for prefix in prefixes:
        if image.startswith(prefix):
            # remove prefix
            aliases.append(image[len(prefix) :])
        else:
            # add prefix
            aliases.append(prefix + image)
    return aliases


def _validate_interactive_session_image(type_: str, user_image: Optional[str]) -> str:
    if type_ not in REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS:
        raise REANAInteractiveSessionError(
            f"Missing environment configuration for {type_}."
        )

    config = REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS[type_]
    # recommended_images can be empty
    recommended_images = REANA_INTERACTIVE_SESSIONS_RECOMMENDED_IMAGES[type_]
    # default_image can be `None`
    default_image = REANA_INTERACTIVE_SESSIONS_DEFAULT_IMAGES[type_]
    image = user_image or default_image

    if not image:
        raise REANAInteractiveSessionError("Container image must be specified.")

    if not config["allow_custom"]:
        # check if one of the aliases is in the recommended list
        aliases = _container_image_aliases(image)
        # normally only one alias should match, unless multiple aliases of the same
        # image are present in the recommended list
        allowed_alias = next(
            (alias for alias in aliases if alias in recommended_images), None
        )
        if not allowed_alias:
            raise REANAInteractiveSessionError(
                f"Custom container image {image} is not allowed."
            )
        return allowed_alias
    else:
        return image


class WorkflowRunManager:
    """Interface which specifies how to manage workflow runs."""

    if os.getenv("FLASK_ENV") == "development":
        WORKFLOW_ENGINE_COMMON_ENV_VARS.extend(DEBUG_ENV_VARS)

    engine_mapping = {
        "cwl": {
            "image": "{}".format(REANA_WORKFLOW_ENGINE_IMAGE_CWL),
            "command": (
                "run-cwl-workflow "
                "--workflow-uuid {id} "
                "--workflow-workspace {workspace} "
                "--workflow-json '{workflow_json}' "
                "--workflow-file '{workflow_file}' "
                "--workflow-parameters '{parameters}' "
                "--operational-options '{options}' "
            ),
            "environment_variables": WORKFLOW_ENGINE_COMMON_ENV_VARS
            + WORKFLOW_ENGINE_CWL_ENV_VARS,
        },
        "yadage": {
            "image": "{}".format(REANA_WORKFLOW_ENGINE_IMAGE_YADAGE),
            "command": (
                "run-yadage-workflow "
                "--workflow-uuid {id} "
                "--workflow-workspace {workspace} "
                "--workflow-json '{workflow_json}' "
                "--workflow-file '{workflow_file}' "
                "--workflow-parameters '{parameters}' "
                "--operational-options '{options}' "
            ),
            "environment_variables": WORKFLOW_ENGINE_COMMON_ENV_VARS
            + WORKFLOW_ENGINE_YADAGE_ENV_VARS,
        },
        "serial": {
            "image": "{}".format(REANA_WORKFLOW_ENGINE_IMAGE_SERIAL),
            "command": (
                "run-serial-workflow "
                "--workflow-uuid {id} "
                "--workflow-workspace {workspace} "
                "--workflow-json '{workflow_json}' "
                "--workflow-parameters '{parameters}' "
                "--operational-options '{options}' "
            ),
            "environment_variables": WORKFLOW_ENGINE_COMMON_ENV_VARS
            + WORKFLOW_ENGINE_SERIAL_ENV_VARS,
        },
        "snakemake": {
            "image": "{}".format(REANA_WORKFLOW_ENGINE_IMAGE_SNAKEMAKE),
            "command": (
                "run-snakemake-workflow "
                "--workflow-uuid {id} "
                "--workflow-workspace {workspace} "
                "--workflow-file '{workflow_file}' "
                "--workflow-parameters '{parameters}' "
                "--operational-options '{options}' "
            ),
            "environment_variables": WORKFLOW_ENGINE_COMMON_ENV_VARS
            + WORKFLOW_ENGINE_SNAKEMAKE_ENV_VARS,
        },
    }
    """Mapping between engines and their basis configuration."""

    def __init__(self, workflow):
        """Initialise a WorkflowRunManager.

        :param workflow: An instance of :class:`reana_db.models.Workflow`.
        """
        self.workflow = workflow

    def _workflow_run_name_generator(self, mode):
        """Generate the name to be given to a workflow run.

        :param mode: Mode in which the workflow runs: ``workflow`` or
            ``session``.
        """
        return build_unique_component_name(f"run-{mode}", self.workflow.id_)

    def _generate_interactive_workflow_path(self):
        """Generate the path to access the interactive workflow."""
        return "/{}".format(self.workflow.id_)

    def _get_merged_workflow_input_parameters(self, overwrite=None):
        """Return workflow input parameters merged with live ones, if given."""
        overwrite = overwrite or {}
        input_parameters = dict(self.workflow.get_input_parameters(), **overwrite)
        if self.workflow.input_parameters:
            input_parameters = dict(input_parameters, **self.workflow.input_parameters)
        return input_parameters

    def _get_merged_workflow_operational_options(self, overwrite=None):
        """Return workflow input parameters merged with live ones, if given."""
        overwrite = overwrite or {}
        return dict(self.workflow.operational_options, **overwrite)

    def start_batch_workflow_run(
        self, overwrite_input_params=None, overwrite_operational_options=None
    ):
        """Start a batch workflow run."""
        raise NotImplementedError("")

    def start_interactive_session(self):
        """Start an interactive workflow run."""
        raise NotImplementedError("")

    def stop_batch_workflow_run(self):
        """Stop a batch workflow run."""
        raise NotImplementedError("")

    def _workflow_engine_image(self):
        """Return the correct image for the current workflow type."""
        return WorkflowRunManager.engine_mapping[self.workflow.type_]["image"]

    def _workflow_engine_command(
        self, overwrite_input_parameters=None, overwrite_operational_options=None
    ):
        """Return the command to be run for a given workflow engine."""
        return WorkflowRunManager.engine_mapping[self.workflow.type_]["command"].format(
            id=self.workflow.id_,
            workspace=self.workflow.workspace_path,
            workflow_json=base64.standard_b64encode(
                json.dumps(self.workflow.get_specification()).encode()
            ),
            workflow_file=self.workflow.reana_specification.get("workflow").get("file"),
            parameters=base64.standard_b64encode(
                json.dumps(
                    self._get_merged_workflow_input_parameters(
                        overwrite=overwrite_input_parameters
                    )
                ).encode()
            ),
            options=base64.standard_b64encode(
                json.dumps(
                    self._get_merged_workflow_operational_options(
                        overwrite=overwrite_operational_options
                    )
                ).encode()
            ),
        )

    def retrieve_required_cvmfs_repos(self):
        """Build the list of needed CVMFS repos."""
        required_resources = self.workflow.reana_specification["workflow"].get(
            "resources", {}
        )
        return required_resources.get("cvmfs", [])

    def _workflow_engine_env_vars(self):
        """Return necessary environment variables for the workflow engine."""
        env_vars = copy.deepcopy(
            WorkflowRunManager.engine_mapping[self.workflow.type_][
                "environment_variables"
            ]
        )
        env_vars.extend(
            [
                {"name": "REANA_USER_ID", "value": str(self.workflow.owner_id)},
                {
                    "name": "REANA_WORKFLOW_KERBEROS",
                    "value": str(self.requires_kerberos()),
                },
            ]
        )

        cvmfs_volumes = self.retrieve_required_cvmfs_repos()
        if cvmfs_volumes:
            env_vars.append(
                {
                    "name": "REANA_MOUNT_CVMFS",
                    "value": str(cvmfs_volumes),
                }
            )

        return env_vars

    def get_workflow_running_jobs(self):
        """Get all running jobs of a workflow.

        :return: A list of :class:`reana_db.models.Job` instances.
        """
        session = Session.object_session(self.workflow)
        rows = session.query(Job).filter_by(
            workflow_uuid=str(self.workflow.id_), status=JobStatus.running
        )
        return rows.all()

    def get_workflow_running_jobs_as_backend_ids(self):
        """Get all running jobs of a workflow as backend job IDs."""
        return [j.backend_job_id for j in self.get_workflow_running_jobs()]

    def requires_kerberos(self) -> bool:
        """Check whether Kerberos is necessary to run the workflow engine."""
        return (
            self.workflow.reana_specification["workflow"]
            .get("resources", {})
            .get("kerberos", False)
        )

    def requires_voms_proxy(self) -> bool:
        """Check whether Voms_proxy is necessary to run the workflow engine."""
        return (
            self.workflow.reana_specification["workflow"]
            .get("resources", {})
            .get("voms_proxy", False)
        )

    def requires_rucio(self) -> bool:
        """Check whether Rucio is necessary to run the workflow engine."""
        return (
            self.workflow.reana_specification["workflow"]
            .get("resources", {})
            .get("rucio", False)
        )


class KubernetesWorkflowRunManager(WorkflowRunManager):
    """Implementation of WorkflowRunManager for Kubernetes."""

    def start_batch_workflow_run(
        self, overwrite_input_params=None, overwrite_operational_options=None
    ):
        """Start a batch workflow run.

        :param overwrite_input_params: Dictionary with parameters to be
            overwritten or added to the current workflow run.
        :param type: Dict
        :param overwrite_operational_options: Dictionary with operational
            options to be overwritten or added to the current workflow run.
        :param type: Dict
        """
        workflow_run_name = self._workflow_run_name_generator("batch")
        job = self._create_job_spec(
            workflow_run_name,
            overwrite_input_parameters=overwrite_input_params,
            overwrite_operational_options=overwrite_operational_options,
        )

        try:
            # Create the dask cluster and required resources

            if requires_dask(self.workflow):
                DaskResourceManager(
                    workflow_id=self.workflow.id_,
                    workflow_spec=self.workflow.reana_specification["workflow"],
                    workflow_workspace=self.workflow.workspace_path,
                    user_id=self.workflow.owner_id,
                    num_of_workers=self.workflow.reana_specification["workflow"]
                    .get("resources", {})
                    .get("dask", {})
                    .get(
                        "number_of_workers",
                        REANA_DASK_CLUSTER_DEFAULT_NUMBER_OF_WORKERS,
                    ),
                    single_worker_memory=self.workflow.reana_specification["workflow"]
                    .get("resources", {})
                    .get("dask", {})
                    .get(
                        "single_worker_memory",
                        REANA_DASK_CLUSTER_DEFAULT_SINGLE_WORKER_MEMORY,
                    ),
                    kerberos=self.requires_kerberos(),
                    voms_proxy=self.requires_voms_proxy(),
                    rucio=self.requires_rucio(),
                ).create_dask_resources()

            current_k8s_batchv1_api_client.create_namespaced_job(
                namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE, body=job
            )

            # Create PVC needed for CVMFS repos
            if self.retrieve_required_cvmfs_repos():
                create_cvmfs_persistent_volume_claim()

        except ApiException as e:
            msg = "Workflow engine/job controller pod " "creation failed {}".format(e)
            logging.error(msg, exc_info=True)
            raise e

    def start_interactive_session(self, interactive_session_type, image=None, **kwargs):
        """Start an interactive workflow run.

        :param interactive_session_type: One of the available interactive
            session types.
        :param image: Docker image to use for the interactive session.
        :return: Relative path to access the interactive session.
        """
        if interactive_session_type not in InteractiveSessionType.__members__:
            raise REANAInteractiveSessionError(
                f"Interactive type {interactive_session_type} does not exist."
            )

        validated_image = _validate_interactive_session_image(
            interactive_session_type, image
        )

        action_completed = True
        kubernetes_objects = None
        try:
            access_path = self._generate_interactive_workflow_path()
            workflow_run_name = self._workflow_run_name_generator("session")
            kubernetes_objects = build_interactive_k8s_objects[
                interactive_session_type
            ](
                workflow_run_name,
                self.workflow.workspace_path,
                access_path,
                validated_image,
                access_token=self.workflow.get_owner_access_token(),
                cvmfs_repos=self.retrieve_required_cvmfs_repos(),
                owner_id=self.workflow.owner_id,
                workflow_id=self.workflow.id_,
                **kwargs,
            )

            # Create PVC needed for CVMFS repos
            if self.retrieve_required_cvmfs_repos():
                create_cvmfs_persistent_volume_claim()

            instantiate_chained_k8s_objects(
                kubernetes_objects, REANA_RUNTIME_KUBERNETES_NAMESPACE
            )

            # Save interactive session to the database
            int_session = InteractiveSession(
                name=workflow_run_name,
                path=access_path,
                type_=interactive_session_type,
                owner_id=self.workflow.owner_id,
            )
            self.workflow.sessions.append(int_session)
            current_db_sessions = Session.object_session(self.workflow)
            current_db_sessions.add(self.workflow)
            current_db_sessions.commit()

            return access_path

        except KeyError:
            action_completed = False
            raise REANAInteractiveSessionError(
                "Unsupported interactive session type {}.".format(
                    interactive_session_type
                )
            )
        except ApiException as api_exception:
            action_completed = False
            raise REANAInteractiveSessionError(
                "Connection to Kubernetes has failed:\n{}".format(api_exception)
            )
        except Exception as e:
            action_completed = False
            raise REANAInteractiveSessionError(
                "Unkown error while starting interactive workflow run:\n{}".format(e)
            )
        finally:
            if not action_completed and kubernetes_objects:
                delete_k8s_objects_if_exist(
                    kubernetes_objects, REANA_RUNTIME_KUBERNETES_NAMESPACE
                )

    def stop_interactive_session(self, interactive_session_id):
        """Stop an interactive workflow run."""
        int_session = InteractiveSession.query.filter_by(
            id_=interactive_session_id
        ).first()

        if not int_session:
            raise REANAInteractiveSessionError(
                "Interactive session for workflow {} does not exist.".format(
                    self.workflow.name
                )
            )
        action_completed = True
        try:
            delete_k8s_ingress_object(
                ingress_name=int_session.name,
                namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
            )
        except Exception as e:
            action_completed = False
            raise REANAInteractiveSessionError(
                "Unkown error while stopping interactive session:\n{}".format(e)
            )
        finally:
            if action_completed:
                # TODO: once multiple sessions will be supported instead of
                # deleting a session, its status should be changed to "stopped"
                # int_session.status = RunStatus.stopped
                current_db_sessions = Session.object_session(self.workflow)
                current_db_sessions.delete(int_session)
                current_db_sessions.commit()

    def _delete_k8s_job_quiet(self, job_name):
        """Delete a Kubernetes job.

        This method will not raise an exception if the deletion fails, but will
        only log the error.

        :param job_name: Name of the Kubernetes job to be deleted.
        :type job_name: str
        :return: True if the job was deleted successfully, False otherwise.
        """
        try:
            current_k8s_batchv1_api_client.delete_namespaced_job(
                job_name,
                REANA_RUNTIME_KUBERNETES_NAMESPACE,
                body=V1DeleteOptions(
                    grace_period_seconds=0, propagation_policy="Background"
                ),
            )
        except ApiException:
            logging.error(
                f"Error while trying to stop {self.workflow.id_}"
                f": Kubernetes job {job_name} could not be deleted.",
                exc_info=True,
            )
            return False
        return True

    def stop_batch_workflow_run(self):
        """Stop a batch workflow run along with all its dependent jobs."""
        workflow_run_name = self._workflow_run_name_generator("batch")
        self._delete_k8s_job_quiet(workflow_run_name)

    def _create_job_spec(
        self,
        name,
        command=None,
        image=None,
        env_vars=None,
        overwrite_input_parameters=None,
        overwrite_operational_options=None,
    ):
        """Instantiate a Kubernetes job.

        :param name: Name of the job.
        :param image: Docker image to use to run the job on.
        :param command: List of commands to run on the given job.
        :param env_vars: List of environment variables (dictionaries) to
            inject into the workflow engine container.
        :param interactive_session_type: One of the available interactive
            session types.
        :param overwrite_input_params: Dictionary with parameters to be
            overwritten or added to the current workflow run.
        :param type: Dict
        :param overwrite_operational_options: Dictionary with operational
            options to be overwritten or added to the current workflow run.
        :param type: Dict
        """
        image = image or self._workflow_engine_image()
        command = command or self._workflow_engine_command(
            overwrite_input_parameters=overwrite_input_parameters,
            overwrite_operational_options=overwrite_operational_options,
        )
        workflow_engine_env_vars = env_vars or self._workflow_engine_env_vars()
        owner_id = str(self.workflow.owner_id)
        command = format_cmd(command)
        workspace_mount, workspace_volume = get_workspace_volume(
            self.workflow.workspace_path
        )

        workflow_metadata = client.V1ObjectMeta(
            name=name,
            labels={
                "reana_workflow_mode": "batch",
                "reana-run-batch-workflow-uuid": str(self.workflow.id_),
            },
            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
        )

        user_secrets = UserSecretsStore.fetch(owner_id)
        kerberos = None
        if self.requires_kerberos():
            kerberos = get_kerberos_k8s_config(
                user_secrets,
                kubernetes_uid=WORKFLOW_RUNTIME_USER_UID,
            )

        job = client.V1Job()
        job.api_version = "batch/v1"
        job.kind = "Job"
        job.metadata = workflow_metadata
        spec = client.V1JobSpec(template=client.V1PodTemplateSpec())
        spec.template.metadata = workflow_metadata

        workflow_engine_container = client.V1Container(
            name=current_app.config["WORKFLOW_ENGINE_NAME"],
            image=image,
            image_pull_policy="IfNotPresent",
            env=[],
            volume_mounts=[],
            command=["/bin/bash", "-c"],
            args=command,
        )

        workflow_engine_env_vars.extend(
            [
                {
                    "name": "REANA_JOB_CONTROLLER_SERVICE_PORT_HTTP",
                    "value": str(current_app.config["JOB_CONTROLLER_CONTAINER_PORT"]),
                },
                {"name": "REANA_JOB_CONTROLLER_SERVICE_HOST", "value": "localhost"},
                {"name": "REANA_COMPONENT_PREFIX", "value": REANA_COMPONENT_PREFIX},
                {
                    "name": "REANA_COMPONENT_NAMING_SCHEME",
                    "value": REANA_COMPONENT_NAMING_SCHEME,
                },
                {
                    "name": "REANA_INFRASTRUCTURE_KUBERNETES_NAMESPACE",
                    "value": REANA_INFRASTRUCTURE_KUBERNETES_NAMESPACE,
                },
                {
                    "name": "REANA_RUNTIME_KUBERNETES_NAMESPACE",
                    "value": REANA_RUNTIME_KUBERNETES_NAMESPACE,
                },
                {
                    "name": "REANA_JOB_CONTROLLER_CONNECTION_CHECK_SLEEP",
                    "value": str(REANA_JOB_CONTROLLER_CONNECTION_CHECK_SLEEP),
                },
            ]
        )
        workflow_engine_container.env.extend(workflow_engine_env_vars)
        workflow_engine_container.security_context = client.V1SecurityContext(
            run_as_group=WORKFLOW_RUNTIME_USER_GID,
            run_as_user=WORKFLOW_RUNTIME_USER_UID,
            allow_privilege_escalation=False,
        )
        workflow_engine_container.volume_mounts = [workspace_mount]

        if kerberos:
            workflow_engine_container.volume_mounts += kerberos.volume_mounts
            workflow_engine_container.env += kerberos.env

        job_controller_env_secrets = user_secrets.get_env_secrets_as_k8s_spec()

        user_secret = user_secrets.get_secret("CERN_USER")
        user = user_secret.value_str if user_secret else WORKFLOW_RUNTIME_USER_NAME

        job_controller_container = client.V1Container(
            name=current_app.config["JOB_CONTROLLER_NAME"],
            image=current_app.config["JOB_CONTROLLER_IMAGE"],
            image_pull_policy="IfNotPresent",
            env=[],
            volume_mounts=[],
            command=["/bin/bash", "-c"],
            args=self._create_job_controller_startup_cmd(user),
            ports=[],
            # Make sure that all the jobs are stopped before the deletion of the run-batch pod
            lifecycle=client.V1Lifecycle(
                pre_stop=client.V1Handler(
                    http_get=client.V1HTTPGetAction(
                        port=JOB_CONTROLLER_CONTAINER_PORT,
                        path=JOB_CONTROLLER_SHUTDOWN_ENDPOINT,
                    )
                )
            ),
        )

        job_controller_container.env.extend(
            [
                {"name": "REANA_USER_ID", "value": owner_id},
                {"name": "CERN_USER", "value": user},
                {"name": "USER", "value": user},  # Required by HTCondor
                {"name": "K8S_CERN_EOS_AVAILABLE", "value": K8S_CERN_EOS_AVAILABLE},
                {"name": "IMAGE_PULL_SECRETS", "value": ",".join(IMAGE_PULL_SECRETS)},
                {
                    "name": "REANA_SQLALCHEMY_DATABASE_URI",
                    "value": SQLALCHEMY_DATABASE_URI,
                },
                # reduce the number of open database connections kept in the pool
                {"name": "SQLALCHEMY_POOL_SIZE", "value": "1"},
                {"name": "REANA_STORAGE_BACKEND", "value": REANA_STORAGE_BACKEND},
                {"name": "REANA_COMPONENT_PREFIX", "value": REANA_COMPONENT_PREFIX},
                {
                    "name": "REANA_COMPONENT_NAMING_SCHEME",
                    "value": REANA_COMPONENT_NAMING_SCHEME,
                },
                {
                    "name": "REANA_INFRASTRUCTURE_KUBERNETES_NAMESPACE",
                    "value": REANA_INFRASTRUCTURE_KUBERNETES_NAMESPACE,
                },
                {
                    "name": "REANA_RUNTIME_KUBERNETES_NAMESPACE",
                    "value": REANA_RUNTIME_KUBERNETES_NAMESPACE,
                },
                {
                    "name": "REANA_JOB_HOSTPATH_MOUNTS",
                    "value": json.dumps(REANA_JOB_HOSTPATH_MOUNTS),
                },
                {
                    "name": "REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES",
                    "value": ",".join(
                        REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES
                    ),
                },
                {
                    "name": "REANA_KUBERNETES_JOBS_MEMORY_LIMIT",
                    "value": REANA_KUBERNETES_JOBS_MEMORY_LIMIT,
                },
                {
                    "name": "REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT",
                    "value": REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT,
                },
                {
                    "name": "REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT",
                    "value": REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT,
                },
                {
                    "name": "REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT",
                    "value": REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT,
                },
                {"name": "WORKSPACE_PATHS", "value": json.dumps(WORKSPACE_PATHS)},
            ]
        )
        # env vars coming from Helm values are added after the ones from r-w-controller
        # so that the former can override the latter in case of necessity
        job_controller_container.env.extend(copy.deepcopy(JOB_CONTROLLER_ENV_VARS))
        job_controller_container.env.extend(job_controller_env_secrets)
        if REANA_RUNTIME_JOBS_KUBERNETES_NODE_LABEL:
            job_controller_container.env.append(
                {
                    "name": "REANA_RUNTIME_JOBS_KUBERNETES_NODE_LABEL",
                    "value": os.getenv("REANA_RUNTIME_JOBS_KUBERNETES_NODE_LABEL"),
                },
            )
        if requires_dask(self.workflow):
            job_controller_container.env.append(
                {
                    "name": "DASK_SCHEDULER_URI",
                    "value": get_dask_component_name(
                        self.workflow.id_,
                        "dashboard_service_uri",
                        REANA_RUNTIME_KUBERNETES_NAMESPACE,
                    ),
                },
            )

        secrets_volume_mount = user_secrets.get_secrets_volume_mount_as_k8s_spec()
        job_controller_container.volume_mounts = [workspace_mount, secrets_volume_mount]

        job_controller_container.ports = [
            {"containerPort": current_app.config["JOB_CONTROLLER_CONTAINER_PORT"]}
        ]
        containers = [workflow_engine_container, job_controller_container]
        spec.template.spec = client.V1PodSpec(
            containers=containers,
            node_selector=REANA_RUNTIME_BATCH_KUBERNETES_NODE_LABEL,
            init_containers=[],
            termination_grace_period_seconds=REANA_RUNTIME_BATCH_TERMINATION_GRACE_PERIOD,
        )
        spec.template.spec.service_account_name = (
            REANA_RUNTIME_KUBERNETES_SERVICEACCOUNT_NAME
        )
        volumes = [
            workspace_volume,
            user_secrets.get_file_secrets_volume_as_k8s_specs(),
        ]

        if kerberos:
            volumes += kerberos.volumes
            spec.template.spec.init_containers.append(kerberos.init_container)

        # filter out volumes with the same name
        spec.template.spec.volumes = list({v["name"]: v for v in volumes}.values())

        if os.getenv("FLASK_ENV") == "development":
            code_volume_name = "reana-code"
            code_mount_path = "/code"
            k8s_code_volume = client.V1Volume(name=code_volume_name)
            k8s_code_volume.host_path = client.V1HostPathVolumeSource(code_mount_path)
            spec.template.spec.volumes.append(k8s_code_volume)

            for container in spec.template.spec.containers:
                container.env.extend(current_app.config["DEBUG_ENV_VARS"])
                sub_path = f"reana-{container.name}"
                if container.name == "workflow-engine":
                    sub_path += f"-{self.workflow.type_}"
                container.volume_mounts.append(
                    {
                        "name": code_volume_name,
                        "mountPath": code_mount_path,
                        "subPath": sub_path,
                    }
                )

        if kerberos:
            spec.template.spec.containers.append(kerberos.renew_container)

        job.spec = spec
        job.spec.template.spec.restart_policy = "Never"

        job.spec.backoff_limit = 0
        return job

    def _create_job_controller_startup_cmd(self, user=None):
        """Create job controller startup cmd."""
        base_cmd = "exec flask run -h 0.0.0.0;"
        if user:
            add_group_cmd = (
                "getent group '{gid}' || groupadd -f -g '{gid}' '{name}';".format(
                    gid=WORKFLOW_RUNTIME_USER_GID, name=WORKFLOW_RUNTIME_GROUP_NAME
                )
            )
            add_user_cmd = "useradd -u {} -g {} -M {};".format(
                WORKFLOW_RUNTIME_USER_UID, WORKFLOW_RUNTIME_USER_GID, user
            )
            chown_workspace_cmd = "chown -R {} {};".format(
                WORKFLOW_RUNTIME_USER_UID,
                self.workflow.workspace_path,
            )
            run_app_cmd = 'exec su {} /bin/bash -c "{}"'.format(user, base_cmd)
            full_cmd = add_group_cmd + add_user_cmd + chown_workspace_cmd + run_app_cmd
            return [full_cmd]
        else:
            return base_cmd.split()
