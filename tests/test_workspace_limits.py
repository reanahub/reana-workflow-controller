# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""Workspace file listing limit tests."""

import uuid
from types import SimpleNamespace

import fs
import pytest
from flask import Flask

from reana_workflow_controller.rest import workflows_workspace


@pytest.fixture()
def app():
    """Create a minimal Flask app for request context tests."""
    return Flask(__name__)


def _create_csv_files(workspace_path, count):
    """Create a number of CSV files in unique subdirectories."""
    fs_ = fs.open_fs(str(workspace_path))
    for i in range(count):
        subdir_name = str(uuid.uuid4())
        fs_.makedirs(subdir_name)
        fs_.touch(f"{subdir_name}/{i}.csv")


def _create_files(workspace_path, paths):
    """Create files with explicit relative paths."""
    fs_ = fs.open_fs(str(workspace_path))
    for path in paths:
        directory = fs.path.dirname(path)
        if directory:
            fs_.makedirs(directory, recreate=True)
        fs_.touch(path)


def _mock_workspace_access(monkeypatch, workspace_path):
    """Mock user and workflow lookups for workspace route tests."""

    class _UserQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(id_="user-1")

    monkeypatch.setattr(workflows_workspace.User, "query", _UserQuery(), raising=False)
    monkeypatch.setattr(
        workflows_workspace,
        "_get_workflow_with_uuid_or_name",
        lambda *args, **kwargs: SimpleNamespace(
            id_="workflow-id",
            workspace_path=str(workspace_path),
        ),
    )


def test_get_files_returns_400_when_display_limit_is_exceeded(
    app,
    tmp_path,
    monkeypatch,
):
    """Test get files list returns 400 when display limit is exceeded."""
    monkeypatch.setattr(
        "reana_workflow_controller.rest.utils.WORKSPACE_DISPLAY_FILE_LIMIT", 3
    )
    _mock_workspace_access(monkeypatch, tmp_path)

    _create_csv_files(tmp_path, count=4)

    with app.test_request_context(
        "/workflows/workflow-id/workspace",
        query_string={"user": "user-1"},
    ):
        response, status_code = workflows_workspace.get_files.__wrapped__(
            "workflow-id",
            paginate=lambda items: {"items": items, "total": len(items)},
        )

        assert status_code == 400
        assert response.get_json() == {
            "message": "Too many files to display (limit=3). Please use more "
            "specific filters to narrow the results. Available filters: file "
            "name, size, or last-modified."
        }


def test_get_files_with_wildcard_returns_400_when_display_limit_is_exceeded(
    app,
    tmp_path,
    monkeypatch,
):
    """Test wildcard file listing returns 400 when display limit is exceeded."""
    monkeypatch.setattr(
        "reana_workflow_controller.rest.utils.WORKSPACE_DISPLAY_FILE_LIMIT", 3
    )
    _mock_workspace_access(monkeypatch, tmp_path)

    _create_csv_files(tmp_path, count=4)
    fs.open_fs(str(tmp_path)).touch("notes.txt")

    with app.test_request_context(
        "/workflows/workflow-id/workspace",
        query_string={"user": "user-1", "file_name": "**/*.csv"},
    ):
        response, status_code = workflows_workspace.get_files.__wrapped__(
            "workflow-id",
            paginate=lambda items: {"items": items, "total": len(items)},
        )

        assert status_code == 400
        assert response.get_json() == {
            "message": "Too many files to display (limit=3). Please use more "
            "specific filters to narrow the results. Available filters: file "
            "name, size, or last-modified."
        }


def test_get_files_returns_filtered_files_when_matches_are_within_display_limit(
    app,
    tmp_path,
    monkeypatch,
):
    """Test filtered file listing returns matches below the display limit."""
    monkeypatch.setattr(
        "reana_workflow_controller.rest.utils.WORKSPACE_DISPLAY_FILE_LIMIT", 10
    )
    _mock_workspace_access(monkeypatch, tmp_path)

    _create_files(
        tmp_path,
        [
            "plotting/jpt_1.pdf",
            "plotting/pt_1.png",
            "plotting/pt_1.pdf",
            "plotting/jpt_1.png",
            "plotting/pt_2.pdf",
            "plotting/pt_3.pdf",
            "logs/run.log",
            "results/data.root",
            "results/table.csv",
            "notes/readme.txt",
            "other/a.txt",
            "other/b.txt",
        ],
    )

    with app.test_request_context(
        "/workflows/workflow-id/workspace",
        query_string={
            "user": "user-1",
            "search": '{"name":["pt_1"]}',
        },
    ):
        response, status_code = workflows_workspace.get_files.__wrapped__(
            "workflow-id",
            paginate=lambda items: {"items": items, "total": len(items)},
        )

        assert status_code == 200
        assert response.get_json()["total"] == 4
        assert sorted(item["name"] for item in response.get_json()["items"]) == sorted(
            [
                "plotting/jpt_1.pdf",
                "plotting/pt_1.png",
                "plotting/pt_1.pdf",
                "plotting/jpt_1.png",
            ]
        )


def test_get_files_with_wildcard_returns_filtered_files_when_matches_are_within_display_limit(
    app,
    tmp_path,
    monkeypatch,
):
    """Test filtered wildcard listing returns matches below the display limit."""
    monkeypatch.setattr(
        "reana_workflow_controller.rest.utils.WORKSPACE_DISPLAY_FILE_LIMIT", 10
    )
    _mock_workspace_access(monkeypatch, tmp_path)

    _create_files(
        tmp_path,
        [
            "plotting/jpt_1.pdf",
            "plotting/pt_1.png",
            "plotting/pt_1.pdf",
            "plotting/jpt_1.png",
            "plotting/pt_2.pdf",
            "plotting/pt_3.pdf",
            "plotting/summary.txt",
            "logs/run.log",
            "other/a.txt",
            "other/b.txt",
            "other/c.txt",
            "other/d.txt",
        ],
    )

    with app.test_request_context(
        "/workflows/workflow-id/workspace",
        query_string={
            "user": "user-1",
            "file_name": "plotting/*",
            "search": '{"name":["pt_1"]}',
        },
    ):
        response, status_code = workflows_workspace.get_files.__wrapped__(
            "workflow-id",
            paginate=lambda items: {"items": items, "total": len(items)},
        )

        assert status_code == 200
        assert response.get_json()["total"] == 4
        assert sorted(item["name"] for item in response.get_json()["items"]) == sorted(
            [
                "plotting/jpt_1.pdf",
                "plotting/pt_1.png",
                "plotting/pt_1.pdf",
                "plotting/jpt_1.png",
            ]
        )


def test_get_files_returns_400_for_malformed_search_payload(
    app,
    tmp_path,
    monkeypatch,
):
    """Test malformed search payload returns 400 instead of REANA_WORKON 404."""
    _mock_workspace_access(monkeypatch, tmp_path)

    with app.test_request_context(
        "/workflows/workflow-id/workspace",
        query_string={"user": "user-1", "search": "{"},
    ):
        response, status_code = workflows_workspace.get_files.__wrapped__(
            "workflow-id",
            paginate=lambda items: {"items": items, "total": len(items)},
        )

        assert status_code == 400
        assert response.get_json() == {"message": "Malformed request."}
