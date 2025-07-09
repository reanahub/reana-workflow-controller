# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2025, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

import importlib

import pytest

import reana_workflow_controller.config as config


def _reload_config():
    """Reload configuration module after environment changes."""
    return importlib.reload(config)


def test_parse_comma_separated_list():
    assert config._parse_comma_separated_list("") == []
    assert config._parse_comma_separated_list("ls") == ["ls"]
    assert config._parse_comma_separated_list("ls,list") == ["ls", "list"]
    assert config._parse_comma_separated_list(" ls, list ,rm,, ") == [
        "ls",
        "list",
        "rm",
    ]

    parsed = config._parse_comma_separated_list("ls,list")
    assert "ls" in parsed
    assert "list" in parsed
    assert "l" not in parsed  # ensures no more substring matching


def test_force_garbage_collection_rejects_invalid_values(monkeypatch):
    """Test FORCE_GARBAGE_COLLECTION rejects unsupported command values."""
    with monkeypatch.context() as m:
        m.setenv("FORCE_GARBAGE_COLLECTION", "lis,delet")
        with pytest.raises(ValueError) as exc_info:
            _reload_config()
        message = str(exc_info.value)
        assert "Invalid FORCE_GARBAGE_COLLECTION values:" in message
        assert "delet" in message
        assert "lis" in message
        assert "Valid values: delete, list, ls, rm" in message

    _reload_config()


def test_force_garbage_collection_accepts_valid_values(monkeypatch):
    """Test FORCE_GARBAGE_COLLECTION accepts supported command values."""
    with monkeypatch.context() as m:
        m.setenv("FORCE_GARBAGE_COLLECTION", "ls,list,rm,delete")
        reloaded_config = _reload_config()
        assert reloaded_config.FORCE_GARBAGE_COLLECTION == [
            "ls",
            "list",
            "rm",
            "delete",
        ]

    _reload_config()
