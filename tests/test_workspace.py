# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2022 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""Workspace utilities tests"""

import os
from contextlib import nullcontext as does_not_raise
from pathlib import Path

import pytest

from reana_workflow_controller import workspace


@pytest.fixture()
def test_workspace(tmp_path: Path):
    """Workspace containing test files."""
    files = [
        "file.yaml",
        "file.txt",
        "dir/subdir/x",
        "dir/subdir/y",
        "dir/z",
    ]
    directories = [
        "empty_dir",
    ]
    symlinks = [
        ("sym", "dir/z"),
        ("symdir", "dir"),
    ]

    for file in files:
        path = tmp_path / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file)

    for directory in directories:
        path = tmp_path / directory
        path.mkdir(parents=True, exist_ok=True)

    for source, target in symlinks:
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(tmp_path / target)

    return tmp_path


@pytest.mark.parametrize(
    "name, expectation",
    [
        ("xyz", does_not_raise()),
        ("file.txt", does_not_raise()),
        ("", pytest.raises(Exception)),
        (".", pytest.raises(Exception)),
        ("..", pytest.raises(Exception)),
        ("/", pytest.raises(Exception)),
        ("/xyz", pytest.raises(Exception)),
        ("xyz/", pytest.raises(Exception)),
    ],
)
def test_validate_path_component(name, expectation):
    """Test the validation of path components."""
    with expectation:
        workspace._validate_path_component(name)


@pytest.mark.parametrize(
    "path, expectation",
    [
        ("file.yaml", does_not_raise()),
        ("empty_dir", does_not_raise()),
        ("dir/subdir", pytest.raises(Exception, match="not a valid path")),
        ("sym", pytest.raises(Exception, match="Symlinks not allowed")),
        ("not_found", pytest.raises(Exception, match="No such file")),
    ],
)
def test_open_single_component(path, expectation, test_workspace):
    """Test opening a file descriptor given fd to the parent directory."""
    dir_fd = os.open(test_workspace, os.O_RDONLY)
    with expectation:
        workspace._open_single_component(path, dir_fd)


@pytest.mark.parametrize(
    "path, expectation",
    [
        ("file.yaml", does_not_raise()),
        ("empty_dir", does_not_raise()),
        ("dir/subdir", does_not_raise()),
        ("dir/subdir/x", does_not_raise()),
        ("sym", pytest.raises(Exception)),
        ("not_found", pytest.raises(Exception)),
    ],
)
def test_open_fd(path, expectation, test_workspace):
    """Open file/directory inside the workspace."""
    with expectation:
        workspace.open_fd(test_workspace, path)


@pytest.mark.parametrize(
    "path, expectation",
    [
        ("file.yaml", does_not_raise()),
        ("dir/subdir/x", does_not_raise()),
        ("empty_dir", pytest.raises(Exception)),
        ("sym", pytest.raises(Exception)),
        ("not_found", pytest.raises(Exception)),
    ],
)
def test_open_file_read(path, expectation, test_workspace):
    """Test opening and reading a file inside the workspace."""
    with expectation:
        with workspace.open_file(test_workspace, path) as f:
            assert f.read() == path


@pytest.mark.parametrize(
    "path, expectation",
    [
        ("file.yaml", does_not_raise()),
        ("dir/subdir/x", does_not_raise()),
        ("not_found", does_not_raise()),
        ("empty_dir", pytest.raises(Exception)),
        ("sym", pytest.raises(Exception)),
    ],
)
def test_open_file_write(path, expectation, test_workspace):
    """Test opening and writing to a file inside the workspace."""
    content = "this is the content of the file"
    with expectation:
        with workspace.open_file(test_workspace, path, mode="w") as f:
            assert f.write(content) == len(content)


@pytest.mark.parametrize(
    "path, expectation",
    [
        ("file.yaml", does_not_raise()),
        ("empty_dir", does_not_raise()),
        ("dir/subdir/x", does_not_raise()),
        ("sym", does_not_raise()),
        ("dir", pytest.raises(Exception, match="not empty")),
        ("not_found", pytest.raises(Exception)),
    ],
)
def test_delete(path: str, expectation, test_workspace: Path):
    """Test the deletion of files and directories inside the workspace."""
    with expectation:
        workspace.delete(test_workspace, path)
        assert not (test_workspace / path).exists()


def test_delete_symlink(test_workspace: Path):
    """Test that deleting a symlink does not delete the target file."""
    abs_sym = test_workspace / "sym"
    abs_target = abs_sym.parent / os.readlink(abs_sym)

    # Make sure the symlink points to a file
    assert abs_sym.is_file()
    assert abs_sym.is_symlink()
    assert abs_target.is_file()
    assert not abs_target.is_symlink()

    workspace.delete(test_workspace, "sym")

    assert not abs_sym.exists()
    assert abs_target.exists()


@pytest.mark.parametrize(
    "source, target, expectation",
    [
        ("file.yaml", "new_file.yaml", does_not_raise()),
        ("file.yaml", "file.txt", does_not_raise()),  # overwrite file
        ("file.yaml", "sym", does_not_raise()),
        ("file.yaml", "dir", does_not_raise()),
        ("dir", "new_dir", does_not_raise()),
        ("dir", "empty_dir", does_not_raise()),
        ("dir", "file.txt", pytest.raises(Exception, match="Not a directory")),
        ("not_found", "file.txt", pytest.raises(Exception, match="No such file")),
    ],
)
def test_move(source: str, target: str, expectation, test_workspace: Path):
    """Test moving file and directories inside the workspace."""
    abs_source = test_workspace / source
    abs_target = test_workspace / target
    target_is_dir = abs_target.is_dir()
    with expectation:
        workspace.move(test_workspace, source, target)
        assert not abs_source.exists()
        assert abs_target.exists()
        if target_is_dir:
            assert (abs_target / abs_source.name).exists()


def test_move_inside_symlink_directory(test_workspace: Path):
    """Check that it is not possible to move files inside a symlinked directory."""
    abs_sym = test_workspace / "symdir"
    abs_target = abs_sym.parent / os.readlink(abs_sym)
    assert abs_target.is_dir()

    with pytest.raises(Exception, match="Symlinks not allowed"):
        workspace.move(test_workspace, "file.yaml", "symdir/subdir")


@pytest.mark.parametrize(
    "path, expectation",
    [
        ("file.yaml", does_not_raise()),
        ("empty_dir", does_not_raise()),
        ("dir/subdir/x", does_not_raise()),
        ("sym", does_not_raise()),
        ("symdir", does_not_raise()),
        ("symdir/subdir", pytest.raises(Exception, match="Symlinks not allowed")),
        ("not_found", pytest.raises(Exception)),
    ],
)
def test_lstat(path, expectation, test_workspace):
    """Test lstat on files and directories inside the workspace."""
    with expectation:
        st = workspace.lstat(test_workspace, path)
        assert os.path.samestat(st, os.lstat(test_workspace / path))


@pytest.mark.parametrize(
    "path, expectation",
    [
        ("empty_dir", does_not_raise()),
        ("dir", does_not_raise()),
        ("dir/subdir", does_not_raise()),
        ("file.yaml", pytest.raises(Exception, match="Not a directory")),
        ("symdir", pytest.raises(Exception)),
        ("symdir/subdir", pytest.raises(Exception)),
        ("not_found", pytest.raises(Exception)),
    ],
)
def test_walk(path, expectation, test_workspace):
    """Test walking directories in the workspace."""
    with expectation:
        all(workspace.walk(test_workspace, path))


def test_walk_returned_paths(test_workspace):
    """Test that walk returns the right set of paths."""
    r = workspace.walk(test_workspace, "dir")
    assert set(r) == set(["dir/subdir", "dir/subdir/x", "dir/subdir/y", "dir/z"])


def test_walk_exclude_directories(test_workspace):
    """Test that walk returns the right set of paths when excluding directories."""
    r = workspace.walk(test_workspace, include_dirs=False)
    assert set(r) == set(
        [
            "file.yaml",
            "file.txt",
            "dir/subdir/x",
            "dir/subdir/y",
            "dir/z",
            "sym",
            "symdir",
        ]
    )


@pytest.mark.parametrize(
    "path_or_pattern, include_dirs, expected_result",
    [
        ("dir", True, ["dir/subdir", "dir/subdir/x", "dir/subdir/y", "dir/z"]),
        ("sym*", True, ["sym", "symdir"]),
        ("*dir", True, ["symdir", "dir", "empty_dir"]),
        ("*dir", False, ["symdir"]),
        ("file.yaml", True, ["file.yaml"]),
        ("not_found", True, []),
        ("symdir/*", True, []),
        ("dir/*", True, ["dir/subdir", "dir/z"]),
        ("dir/*", False, ["dir/z"]),
    ],
)
def test_glob_or_walk_directory(
    path_or_pattern, include_dirs, expected_result, test_workspace
):
    """Test that globbing returns the correct paths."""
    result = workspace.glob_or_walk_directory(
        test_workspace, path_or_pattern, include_dirs=include_dirs
    )
    assert set(result) == set(expected_result)
