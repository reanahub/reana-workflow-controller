# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2022, 2023, 2025, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-Workflow-Controller utility tests."""

import io
import json
import os
import stat
import subprocess
import uuid
from contextlib import nullcontext as does_not_raise
from pathlib import Path
from types import SimpleNamespace
from typing import ContextManager
from zipfile import ZipFile

import mock
import pytest
from reana_db.database import Session
from reana_db.models import (
    InteractiveSession,
    InteractiveSessionType,
    RunStatus,
    Workflow,
)
from reana_db.utils import (
    get_disk_usage_or_zero,
    store_workflow_disk_quota,
    update_users_disk_quota,
)
from reana_workflow_controller.errors import REANAWorkflowControllerError
from reana_workflow_controller.config import compose_reana_url
from reana_workflow_controller.rest.utils import (
    create_workflow_workspace,
    delete_workflow,
    download_files_recursive_wildcard,
    get_previewable_mime_type,
    get_workspace_diff,
    is_htcondor_file_transfer_path,
    list_directory_files,
    list_files_recursive_wildcard,
    mv_files,
    remove_files_recursive_wildcard,
)
from werkzeug.exceptions import NotFound


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.created,
        RunStatus.failed,
        RunStatus.finished,
        RunStatus.pending,
        RunStatus.stopped,
        RunStatus.deleted,
        pytest.param(RunStatus.running, marks=pytest.mark.xfail(strict=True)),
    ],
)
def test_delete_workflow(app, session, user0, sample_yadage_workflow_in_db, status):
    """Test deletion of a workflow in all possible statuses."""
    sample_yadage_workflow_in_db.status = status
    session.add(sample_yadage_workflow_in_db)
    session.commit()

    delete_workflow(sample_yadage_workflow_in_db)
    assert sample_yadage_workflow_in_db.status == RunStatus.deleted


def test_delete_all_workflow_runs(app, session, user0, yadage_workflow_with_name):
    """Test deletion of all runs of a given workflow."""
    # add 5 workflows in the database with the same name
    for i in range(5):
        workflow = Workflow(
            id_=uuid.uuid4(),
            name=yadage_workflow_with_name["name"],
            owner_id=user0.id_,
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


def test_delete_workflow_with_interactive_session(
    app, session, sample_yadage_workflow_in_db
):
    """Test deletion of a workflow with an open session attached to the workspace."""
    workflow = sample_yadage_workflow_in_db
    create_workflow_workspace(sample_yadage_workflow_in_db.workspace_path)

    # Create an interactive session and attach it to the workflow
    int_session = InteractiveSession(
        name=workflow.name,
        path="",
        type_=InteractiveSessionType(0).name,
        owner_id=workflow.owner_id,
    )
    workflow.sessions.append(int_session)
    session.add(workflow)
    session.commit()

    # Test deletion of a workflow with attached interactive session
    with mock.patch.multiple(
        "reana_workflow_controller.k8s",
        current_k8s_networking_api_client=mock.DEFAULT,
    ):
        response, http_response = delete_workflow(workflow)
        data = json.loads(response.get_data())
        assert "Workflow successfully deleted" in data["message"]
        assert http_response == 200
        assert not workflow.sessions


@pytest.mark.parametrize("workspace", [True, False])
@mock.patch("reana_workflow_controller.rest.utils.store_workflow_disk_quota")
@mock.patch("reana_workflow_controller.rest.utils.update_users_disk_quota")
@mock.patch("reana_db.utils.WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY", "disk")
def test_workspace_deletion(
    mock_update_user_quota,
    mock_update_workflow_quota,
    app,
    session,
    user0,
    sample_yadage_workflow_in_db,
    workspace,
):
    """Test workspace deletion."""
    workflow = sample_yadage_workflow_in_db
    create_workflow_workspace(sample_yadage_workflow_in_db.workspace_path)

    # Add file to the worskpace
    file_size = 123
    file_path = os.path.join(sample_yadage_workflow_in_db.workspace_path, "temp.txt")
    with open(file_path, "w") as f:
        f.write("A" * file_size)

    # Get disk usage
    disk_usage = get_disk_usage_or_zero(sample_yadage_workflow_in_db.workspace_path)
    assert disk_usage

    # Update disk quotas
    store_workflow_disk_quota(sample_yadage_workflow_in_db)
    update_users_disk_quota(sample_yadage_workflow_in_db.owner)

    # check that the workflow workspace exists
    assert os.path.exists(sample_yadage_workflow_in_db.workspace_path)
    delete_workflow(workflow, workspace=workspace)
    if workspace:
        assert not os.path.exists(sample_yadage_workflow_in_db.workspace_path)
        mock_update_user_quota.assert_called_once_with(
            sample_yadage_workflow_in_db.owner,
            bytes_to_sum=-disk_usage,
            override_policy_checks=True,
        )
        mock_update_workflow_quota.assert_called_once_with(
            sample_yadage_workflow_in_db,
            bytes_to_sum=-disk_usage,
            override_policy_checks=True,
        )
    else:
        assert not mock_update_user_quota.called
        assert not mock_update_workflow_quota.called


def test_deletion_of_workspace_of_an_already_deleted_workflow(
    app, session, user0, sample_yadage_workflow_in_db
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
    pattern = "**/*.csv"
    files_to_remove = ["file1.csv", "subdir/file2.csv"]
    files_to_keep = ["file3.md", "subdir/file4.txt"]
    for file_name in files_to_remove + files_to_keep:
        posix_file_path = Path(directory_path, file_name)
        posix_file_path.parent.mkdir(parents=True, exist_ok=True)
        posix_file_path.touch()
        size = posix_file_path.write_bytes(file_binary_content)
        assert posix_file_path.exists()

    deleted_files = remove_files_recursive_wildcard(directory_path, pattern)

    for file_path in files_to_remove:
        assert not Path(directory_path, file_path).exists()
        assert file_path in deleted_files["deleted"]
        assert deleted_files["deleted"][file_path]["size"] == size
    for file_path in files_to_keep:
        assert Path(directory_path, file_path).exists()
        assert file_path not in deleted_files["deleted"]
    assert not len(deleted_files["failed"])


def test_list_recursive_wildcard(tmp_shared_volume_path):
    """Test recursive wildcard deletion of files."""
    file_binary_content = b"1,2,3,4\n5,6,7,8"
    directory_path = Path(tmp_shared_volume_path, "ls_files_test")
    files_to_list = ["file1.csv", "subdir/file2.csv", "file3.txt", "subdir/file4.txt"]
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


@pytest.mark.parametrize(
    "path, expected",
    [
        ("reana_job.123.filetransfer", True),
        ("reana_job.123.filetransfer/credential.cc", True),
        ("./reana_job.123.filetransfer/credential.cc", True),
        ("output/../reana_job.123.filetransfer/credential.cc", True),
        ("../reana_job.123.filetransfer/credential.cc", True),
        ("output/reana_job.123.filetransfer/result.txt", False),
        ("reana_job.123.filetransfer.txt", False),
        ("result.txt", False),
    ],
)
def test_is_htcondor_file_transfer_path(path, expected):
    """Test recognising internal HTCondor file-transfer paths."""
    assert is_htcondor_file_transfer_path(path) is expected


def test_workspace_file_listings_hide_htcondor_file_transfer_directory(
    tmp_shared_volume_path,
):
    """Test hiding internal HTCondor file-transfer directories from listings."""
    workspace_path = Path(tmp_shared_volume_path, "htcondor-listing-test")
    visible_file = workspace_path / "result.txt"
    internal_file = workspace_path / "reana_job.123.filetransfer" / "credential.cc"
    nested_file = (
        workspace_path / "output" / "reana_job.123.filetransfer" / "user-result.txt"
    )
    for path in (visible_file, internal_file, nested_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name)

    listed_files = list_directory_files(workspace_path)
    listed_names = {file_["name"] for file_ in listed_files}
    assert listed_names == {
        "result.txt",
        "output/reana_job.123.filetransfer/user-result.txt",
    }

    listed_files = list_files_recursive_wildcard(workspace_path, "**/*")
    listed_names = {file_["name"] for file_ in listed_files}
    assert listed_names == {
        "output",
        "output/reana_job.123.filetransfer",
        "output/reana_job.123.filetransfer/user-result.txt",
        "result.txt",
    }


def test_workspace_downloads_hide_htcondor_file_transfer_directory(
    app, tmp_shared_volume_path
):
    """Test excluding internal HTCondor file-transfer files from downloads."""
    workspace_path = Path(tmp_shared_volume_path, "htcondor-download-test")
    files = {
        "first.txt": b"first result",
        "second.txt": b"second result",
        "reana_job.123.filetransfer/credential.cc": b"kerberos credential",
    }
    for file_name, contents in files.items():
        path = workspace_path / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    with app.test_request_context("/?preview=false"):
        response = download_files_recursive_wildcard("workflow.1", workspace_path, "")
        response.direct_passthrough = False
        with ZipFile(io.BytesIO(response.get_data())) as archive:
            assert set(archive.namelist()) == {"first.txt", "second.txt"}

        response = download_files_recursive_wildcard(
            "workflow.1", workspace_path, "**/*"
        )
        response.direct_passthrough = False
        with ZipFile(io.BytesIO(response.get_data())) as archive:
            assert set(archive.namelist()) == {"first.txt", "second.txt"}

        with pytest.raises(NotFound):
            download_files_recursive_wildcard(
                "workflow.1",
                workspace_path,
                "reana_job.123.filetransfer/credential.cc",
            )


@pytest.mark.parametrize("contents", ["empty", "empty-subdirectory", "staging-only"])
@pytest.mark.parametrize("pattern", ["", "**/*"])
def test_workspace_downloads_reject_empty_results(app, tmp_path, contents, pattern):
    """Reject downloads that contain no visible files after filtering."""
    if contents == "empty-subdirectory":
        (tmp_path / "output").mkdir()
    elif contents == "staging-only":
        staging = tmp_path / "reana_job.123.filetransfer"
        staging.mkdir()
        (staging / "credential.cc").write_text("credential")

    with app.test_request_context("/?preview=false"), pytest.raises(NotFound):
        download_files_recursive_wildcard("workflow.1", tmp_path, pattern)


@pytest.fixture
def workspace_diff_workflows(tmp_path):
    """Create two empty workspaces for filesystem comparisons."""
    workflows = []
    for run_number in (1, 2):
        workspace_path = tmp_path / str(run_number)
        workspace_path.mkdir()
        workflows.append(
            SimpleNamespace(
                workspace_path=str(workspace_path),
                name="workflow",
                run_number=run_number,
            )
        )
    return workflows


@pytest.mark.parametrize("brief", [False, True])
def test_workspace_diff_filters_only_top_level_entries(workspace_diff_workflows, brief):
    """Preserve nested user data and the native diff output format."""
    for index, workflow in enumerate(workspace_diff_workflows):
        root = Path(workflow.workspace_path)
        nested = root / "output" / "reana_job.123.filetransfer"
        nested.mkdir(parents=True)
        (nested / "result.txt").write_text(f"result {index}\n")
        (root / "result-link").symlink_to(
            "output/reana_job.123.filetransfer/result.txt"
        )
        if index == 0:
            (root / "only-left.txt").write_text("one-sided result\n")
            (root / "different-type").write_text("regular file\n")
        else:
            (root / "different-type").mkdir()

    command = [
        "diff",
        "-q" if brief else "--unified=2",
        "-r",
        *(workflow.workspace_path for workflow in workspace_diff_workflows),
    ]
    expected = subprocess.run(command, capture_output=True, text=True).stdout
    for workflow in workspace_diff_workflows:
        expected = expected.replace(
            workflow.workspace_path, f"{workflow.name}.{workflow.run_number}"
        )
        root = Path(workflow.workspace_path)
        staging = root / "reana_job.123.filetransfer"
        staging.mkdir()
        (staging / "credential.cc").write_text(f"secret {workflow.run_number}\n")
        (root / "reana_job.file.filetransfer").write_text("internal file\n")

    actual = get_workspace_diff(*workspace_diff_workflows, brief=brief, context_lines=2)

    assert actual == expected
    assert "output/reana_job.123.filetransfer/result.txt" in actual
    assert "secret" not in actual


def test_workspace_diff_ignores_new_staging_directories(
    workspace_diff_workflows, monkeypatch
):
    """Do not traverse staging directories created after selecting entries."""
    original_run = subprocess.run
    comparison_paths = []

    def run_after_job_submission(command, **kwargs):
        comparison_paths.extend(command[3:5])
        for workflow in workspace_diff_workflows:
            staging = Path(workflow.workspace_path) / "reana_job.new.filetransfer"
            staging.mkdir()
            (staging / "credential.cc").write_text(f"secret {workflow.run_number}\n")
        return original_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", run_after_job_submission)

    assert get_workspace_diff(*workspace_diff_workflows) == ""
    assert len(comparison_paths) == 2
    assert all(not Path(path).exists() for path in comparison_paths)


def test_workspace_permissions(
    app, session, user0, sample_yadage_workflow_in_db, tmp_shared_volume_path
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


@pytest.mark.parametrize(
    "filename, mime_type",
    [
        ("report.html", "text/html"),
        ("foo/bar/report.html", "text/html"),
        ("results/plot.png", "image/png"),
        ("results/plot.jpeg", "image/jpeg"),
        ("steps/fitdata.root", None),
        ("steps/gendata.c", None),
        ("res/dag.gif", "image/gif"),
    ],
)
def test_get_previewable_mime_type(filename: str, mime_type: str) -> None:
    """Test obtaining previewable mime types from file path."""
    assert get_previewable_mime_type(filename) == mime_type


@pytest.mark.parametrize(
    "source, target, expectation",
    [
        ("a", "c", does_not_raise()),
        ("dir/b", "dir/c", does_not_raise()),
        ("dir", "newdir", does_not_raise()),
        ("a", "dir/b", does_not_raise()),
        ("a", "newdir/a", pytest.raises(REANAWorkflowControllerError)),
        ("not_existing", "c", pytest.raises(REANAWorkflowControllerError)),
        ("/a", "c", pytest.raises(REANAWorkflowControllerError)),
        ("a", "/c", pytest.raises(REANAWorkflowControllerError)),
    ],
)
def test_mv_files(
    source: str,
    target: str,
    expectation: ContextManager,
    sample_serial_workflow_in_db: Workflow,
    tmp_path: Path,
):
    """Test moving files in a workspace."""
    workflow = sample_serial_workflow_in_db
    workspace = tmp_path / "workspace"
    workflow.workspace_path = str(workspace)

    files = ["a", "dir/b"]
    for file in files:
        path = workspace / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file)

    source_path = workspace / source
    target_path = workspace / target

    try:
        source_content = source_path.read_text()
    except (FileNotFoundError, IsADirectoryError):
        source_content = None

    with expectation:
        mv_files(source, target, workflow)
        assert not source_path.exists()
        assert target_path.exists()
        if source_content:
            assert target_path.read_text() == source_content


# Note that this function is inside config.py file and not in
# `rest/utils.py file due to circular import issues.` However,
# it is a utility function so it does not hurt to test it in
# this file.
@pytest.mark.parametrize(
    "hostname, hostport, expected_url",
    [
        ("reana.cern.ch", 443, "https://reana.cern.ch"),
        ("reana.cern.ch", 30443, "https://reana.cern.ch:30443"),
        ("example.com", 443, "https://example.com"),
        ("example.com", 8080, "https://example.com:8080"),
    ],
)
def test_compose_reana_url(hostname, hostport, expected_url):
    """Test composing base reana url."""
    assert compose_reana_url(hostname, hostport) == expected_url
