# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
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
        "SQLALCHEMY_DATABASE_URI": "sqlite:///testdb.db",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "ORGANIZATIONS": ["default"],
    }
    app_ = create_app(config_mapping)
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
    def add_kubernetes_jobs_to_workflow_callable(workflow_uuid, backend=None,
                                                 num_jobs=2):
        """Add Kubernetes jobs to a given workflow.

        :param workflow_uuid: Workflow which the jobs should belong to.
        :param backend: Backend of the created jobs.
        :param num_jobs: Number of jobs to create.
        """
        jobs = []
        backend = backend or 'kubernetes'
        for num in range(num_jobs):
            reana_job_id = uuid.uuid4()
            backend_job_id = uuid.uuid4()
            job = Job(id_=reana_job_id,
                      backend_job_id=str(backend_job_id),
                      workflow_uuid=workflow_uuid)
            session.add(job)
            session.commit()
            jobs.append(job)
        return jobs
    yield add_kubernetes_jobs_to_workflow_callable
