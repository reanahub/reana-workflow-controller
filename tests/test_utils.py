# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-Workflow-Controller utility tests."""

import os
import stat
import uuid
from pathlib import Path

import pytest
from reana_db.models import Job, JobCache, Workflow, RunStatus

from reana_workflow_controller.rest.utils import (
    create_workflow_workspace,
    delete_workflow,
    list_files_recursive_wildcard,
    remove_files_recursive_wildcard,
    stop_workflow,
)


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.created,
        RunStatus.failed,
        RunStatus.finished,
        RunStatus.pending,
        RunStatus.stopped,
        pytest.param(RunStatus.deleted, marks=pytest.mark.xfail),
        pytest.param(RunStatus.running, marks=pytest.mark.xfail),
    ],
)
def test_delete_workflow(
    app, session, default_user, sample_yadage_workflow_in_db, status
):
    """Test deletion of a workflow in all possible statuses."""
    sample_yadage_workflow_in_db.status = status
    session.add(sample_yadage_workflow_in_db)
    session.commit()

    delete_workflow(sample_yadage_workflow_in_db)
    assert sample_yadage_workflow_in_db.status == RunStatus.deleted


def test_delete_all_workflow_runs(
    app, session, default_user, yadage_workflow_with_name
):
    """Test deletion of all runs of a given workflow."""
    # add 5 workflows in the database with the same name
    for i in range(5):
        workflow = Workflow(
            id_=uuid.uuid4(),
            name=yadage_workflow_with_name["name"],
            owner_id=default_user.id_,
            reana_specification=yadage_workflow_with_name["reana_specification"],
            operational_options={},
            type_=yadage_workflow_with_name["reana_specification"]["workflow"]["type"],
            logs="",
        )
        session.add(workflow)
        if i == 4:
            workflow.status = RunStatus.running
            not_deleted_one = workflow.id_
        session.commit()

    first_workflow = (
        session.query(Workflow)
        .filter_by(name=yadage_workflow_with_name["name"])
        .first()
    )
    delete_workflow(first_workflow, all_runs=True)
    for workflow in session.query(Workflow).filter_by(name=first_workflow.name).all():
        if not_deleted_one == workflow.id_:
            assert workflow.status == RunStatus.running
        else:
            assert workflow.status == RunStatus.deleted


@pytest.mark.parametrize("workspace", [True, False])
def test_workspace_deletion(
    app, session, default_user, sample_yadage_workflow_in_db, workspace,
):
    """Test workspace deletion."""
    workflow = sample_yadage_workflow_in_db
    create_workflow_workspace(sample_yadage_workflow_in_db.workspace_path)

    # create a job for the workflow
    workflow_job = Job(id_=uuid.uuid4(), workflow_uuid=workflow.id_)
    job_cache_entry = JobCache(job_id=workflow_job.id_)
    session.add(workflow_job)
    session.commit()
    session.add(job_cache_entry)
    session.commit()

    # create cached workspace
    cache_dir_path = os.path.join(
        sample_yadage_workflow_in_db.workspace_path,
        "..",
        "archive",
        str(workflow_job.id_),
    )

    os.makedirs(cache_dir_path)

    # check that the workflow workspace exists
    assert os.path.exists(sample_yadage_workflow_in_db.workspace_path)
    assert os.path.exists(cache_dir_path)
    delete_workflow(workflow, workspace=workspace)
    if workspace:
        assert not os.path.exists(sample_yadage_workflow_in_db.workspace_path)

    # check that all cache entries for jobs
    # of the deleted workflow are removed
    cache_entries_after_delete = JobCache.query.filter_by(job_id=workflow_job.id_).all()
    assert not cache_entries_after_delete
    assert not os.path.exists(cache_dir_path)


def test_deletion_of_workspace_of_an_already_deleted_workflow(
    app, session, default_user, sample_yadage_workflow_in_db
):
    """Test workspace deletion of an already deleted workflow."""
    create_workflow_workspace(sample_yadage_workflow_in_db.workspace_path)
    # check that the workflow workspace exists
    assert os.path.exists(sample_yadage_workflow_in_db.workspace_path)
    delete_workflow(sample_yadage_workflow_in_db, workspace=False)
    assert os.path.exists(sample_yadage_workflow_in_db.workspace_path)

    delete_workflow(sample_yadage_workflow_in_db, workspace=True)
    assert not os.path.exists(sample_yadage_workflow_in_db.workspace_path)


def test_delete_recursive_wildcard(tmp_shared_volume_path):
    """Test recursive wildcard deletion of files."""
    file_binary_content = b"1,2,3,4\n5,6,7,8"
    size = 0
    directory_path = Path(tmp_shared_volume_path, "rm_files_test")
    files_to_remove = ["file1.csv", "subdir/file2.csv"]
    posix_path_to_deleted_files = []
    for file_name in files_to_remove:
        posix_file_path = Path(directory_path, file_name)
        posix_file_path.parent.mkdir(parents=True)
        posix_file_path.touch()
        size = posix_file_path.write_bytes(file_binary_content)
        assert posix_file_path.exists()
        posix_path_to_deleted_files.append(posix_file_path)

    deleted_files = remove_files_recursive_wildcard(directory_path, "**/*")
    for posix_file_path in posix_path_to_deleted_files:
        assert not posix_file_path.exists()

    for key in files_to_remove:
        assert key in deleted_files["deleted"]
        assert deleted_files["deleted"][key]["size"] == size
    assert not len(deleted_files["failed"])


def test_list_recursive_wildcard(tmp_shared_volume_path):
    """Test recursive wildcard deletion of files."""
    file_binary_content = b"1,2,3,4\n5,6,7,8"
    directory_path = Path(tmp_shared_volume_path, "ls_files_test")
    files_to_list = ["file1.csv", "subdir/file2.csv", "file3.txt"]
    posix_path_to_listed_files = []
    for file_name in files_to_list:
        posix_file_path = Path(directory_path, file_name)
        posix_file_path.parent.mkdir(parents=True, exist_ok=True)
        posix_file_path.touch()
        posix_file_path.write_bytes(file_binary_content)
        assert posix_file_path.exists()
        posix_path_to_listed_files.append(posix_file_path)

    listed_files = list_files_recursive_wildcard(directory_path, "**/*.csv")
    listed_files_names = set(file["name"] for file in listed_files)
    assert listed_files_names == set(
        filter(lambda x: x.endswith(".csv"), files_to_list)
    )

    listed_files = list_files_recursive_wildcard(directory_path, "*.txt")
    listed_files_names = set(file["name"] for file in listed_files)
    assert listed_files_names == set(["file3.txt"])


def test_workspace_permissions(
    app, session, default_user, sample_yadage_workflow_in_db, tmp_shared_volume_path
):
    """Test workspace dir permissions."""
    create_workflow_workspace(sample_yadage_workflow_in_db.workspace_path)
    expected_worspace_permissions = "drwxrwxr-x"
    workspace_permissions = stat.filemode(
        os.stat(sample_yadage_workflow_in_db.workspace_path).st_mode
    )
    assert os.path.exists(sample_yadage_workflow_in_db.workspace_path)
    assert workspace_permissions == expected_worspace_permissions
    delete_workflow(sample_yadage_workflow_in_db, workspace=True)
