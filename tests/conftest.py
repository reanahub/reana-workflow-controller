# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Pytest configuration for REANA-Workflow-Controller."""

from __future__ import absolute_import, print_function

import logging
import os
import shutil
import uuid
import yaml

from flask import current_app
import pytest
from mock import patch
from reana_db.models import (
    Base,
    Job,
    JobStatus,
    User,
    WorkspaceRetentionAuditLog,
    WorkspaceRetentionRule,
)
from reana_commons.k8s.secrets import UserSecretsStore, UserSecrets, Secret

from sqlalchemy_utils import create_database, database_exists, drop_database
from sqlalchemy.orm.attributes import flag_modified

from reana_workflow_controller.config import (
    REANA_INTERACTIVE_SESSIONS_DEFAULT_IMAGES,
    REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS,
    REANA_INTERACTIVE_SESSIONS_RECOMMENDED_IMAGES,
)
from reana_workflow_controller.factory import create_app
from reana_workflow_controller.dask import DaskResourceManager


@pytest.fixture(scope="module")
def base_app(tmp_shared_volume_path):
    """Flask application fixture."""
    config_mapping = {
        "SERVER_NAME": "localhost:5000",
        "SECRET_KEY": "SECRET_KEY",
        "TESTING": True,
        "SHARED_VOLUME_PATH": tmp_shared_volume_path,
        "SQLALCHEMY_DATABASE_URI": os.getenv("REANA_SQLALCHEMY_DATABASE_URI"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "FLASK_ENV": "development",
        "ORGANIZATIONS": ["default"],
    }
    app_ = create_app(config_mapping=config_mapping)
    return app_


@pytest.fixture()
def add_kubernetes_jobs_to_workflow(session):
    """Create and add jobs to a workflow.

    This fixture provides a callable which takes the workflow to which the
    created jobs should belong to. It can be parametrized to customize the
    backend of the created jobs and the number of jobs to create.

    .. code-block:: python

        def test_stop_workflow(workflow, add_kubernetes_jobs_to_workflow):
            workflow_jobs = add_kubernetes_jobs_to_workflow(workflow.id_
                                                            backend='htcondor',
                                                            num_jobs=4)
    """

    def add_kubernetes_jobs_to_workflow_callable(
        workflow, backend=None, num_jobs=2, status=None
    ):
        """Add Kubernetes jobs to a given workflow.

        :param workflow_uuid: Workflow which the jobs should belong to.
        :param backend: Backend of the created jobs.
        :param num_jobs: Number of jobs to create.
        :param status: String representing the status of the created jobs,
            by default ``running``.
        """
        jobs = []
        if status and status not in JobStatus.__members__:
            raise ValueError(
                "Unknown status {} use one of {}".format(status, JobStatus.__members__)
            )

        status = status or JobStatus.running.name
        backend = backend or "kubernetes"
        progress_dict = {
            "total": {"job_ids": [], "total": 0},
            JobStatus.running.name: {"job_ids": [], "total": 0},
            JobStatus.failed.name: {"job_ids": [], "total": 0},
            JobStatus.finished.name: {"job_ids": [], "total": 0},
        }
        for num in range(num_jobs):
            reana_job_id = uuid.uuid4()
            backend_job_id = uuid.uuid4()
            job = Job(
                id_=reana_job_id,
                backend_job_id=str(backend_job_id),
                workflow_uuid=workflow.id_,
                status=JobStatus.running,
            )
            progress_dict[status]["job_ids"].append(str(job.id_))
            progress_dict[status]["total"] += 1
            session.add(job)
            jobs.append(job)
        workflow.job_progress = progress_dict
        session.add(workflow)
        session.commit()
        return jobs

    yield add_kubernetes_jobs_to_workflow_callable


@pytest.fixture()
def sample_serial_workflow_with_retention_rule(session, sample_serial_workflow_in_db):
    """Sample workflow with retention rules."""
    workflow = sample_serial_workflow_in_db
    rule = WorkspaceRetentionRule(
        workflow_id=workflow.id_,
        workspace_files="**/*.csv",
        retention_days=42,
    )
    session.add(rule)
    session.commit()

    yield workflow

    session.query(WorkspaceRetentionAuditLog).delete()
    session.delete(rule)
    session.commit()


@pytest.fixture()
def interactive_session_environments(monkeypatch):
    monkeypatch.setitem(
        REANA_INTERACTIVE_SESSIONS_ENVIRONMENTS,
        "jupyter",
        {
            "recommended": [
                {"image": "docker_image_1", "name": "image name 1"},
                {"image": "docker_image_2", "name": "image name 2"},
            ],
            "allow_custom": False,
        },
    )
    monkeypatch.setitem(
        REANA_INTERACTIVE_SESSIONS_DEFAULT_IMAGES, "jupyter", "docker_image_1"
    )
    monkeypatch.setitem(
        REANA_INTERACTIVE_SESSIONS_RECOMMENDED_IMAGES,
        "jupyter",
        {"docker_image_1", "docker_image_2"},
    )


@pytest.fixture()
def sample_serial_workflow_in_db_with_dask(session, sample_serial_workflow_in_db):
    """Sample workflow with Dask resource."""
    workflow = sample_serial_workflow_in_db
    new_reana_spec = workflow.reana_specification.copy()
    new_reana_spec["workflow"]["resources"] = {
        "dask": {
            "image": "coffeateam/coffea-dask-almalinux8",
            "memory": "10M",
        }
    }
    workflow.reana_specification = new_reana_spec
    flag_modified(workflow, "reana_specification")

    session.add(workflow)
    session.commit()

    yield workflow


@pytest.fixture
def mock_user_secrets(monkeypatch):
    user_id = uuid.uuid4()
    user_secrets = UserSecrets(
        user_id=str(user_id),
        k8s_secret_name="k8s-secret",
        secrets=[Secret(name="third_env", type_="env", value="3")],
    )
    monkeypatch.setattr(
        UserSecretsStore,
        "fetch",
        lambda _: user_secrets,
    )
    return user_secrets


@pytest.fixture
def dask_resource_manager(sample_serial_workflow_in_db_with_dask, mock_user_secrets):
    """Fixture to create a DaskResourceManager instance."""
    manager = DaskResourceManager(
        workflow_id="9eef9a08-5629-420d-8e97-29d498d88e20",
        workflow_spec=sample_serial_workflow_in_db_with_dask.reana_specification[
            "workflow"
        ],
        workflow_workspace="/path/to/workspace",
        user_id="user-123",
        num_of_workers=2,
        single_worker_memory="256Mi",
    )
    return manager


@pytest.fixture
def mock_k8s_client():
    with patch(
        "reana_workflow_controller.dask.current_k8s_custom_objects_api_client"
    ) as mock_client:
        mock_client.create_namespaced_custom_object.return_value = None
        yield mock_client
