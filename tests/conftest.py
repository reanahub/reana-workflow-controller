# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Pytest configuration for REANA-Workflow-Controller."""

from __future__ import absolute_import, print_function

import os
import shutil
import uuid

import pytest
from reana_db.models import Base, Job, JobStatus, User
from sqlalchemy_utils import create_database, database_exists, drop_database

from reana_workflow_controller.factory import create_app


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
