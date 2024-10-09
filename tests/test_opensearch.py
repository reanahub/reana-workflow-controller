# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Workflow-Controller OpenSearchLogFetcher tests."""

import pytest
from opensearchpy import OpenSearch
from mock import patch


def test_fetch_workflow_logs():
    """Test OpenSearchLogFetcher.fetch_workflow_logs."""
    from reana_workflow_controller.opensearch import OpenSearchLogFetcher

    with patch.object(
        OpenSearchLogFetcher, "fetch_logs", return_value="some log"
    ) as mock_search:
        os_fetcher = OpenSearchLogFetcher()
        assert os_fetcher.fetch_workflow_logs("wf_id") == "some log"

    mock_search.assert_called_once_with(
        "wf_id",
        "fluentbit-workflow_log",
        "kubernetes.labels.reana-run-batch-workflow-uuid.keyword",
    )


def test_fetch_job_logs():
    """Test OpenSearchLogFetcher.fetch_job_logs."""
    from reana_workflow_controller.opensearch import OpenSearchLogFetcher

    with patch.object(
        OpenSearchLogFetcher, "fetch_logs", return_value="some log"
    ) as mock_search:
        os_fetcher = OpenSearchLogFetcher()
        assert os_fetcher.fetch_job_logs("job_id") == "some log"

    mock_search.assert_called_once_with(
        "job_id", "fluentbit-job_log", "kubernetes.labels.job-name.keyword"
    )


@pytest.mark.parametrize(
    "opensearch_response,expected_logs",
    [
        (
            {
                "took": 3,
                "timed_out": False,
                "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                "hits": {
                    "total": {"value": 0, "relation": "eq"},
                    "max_score": None,
                    "hits": [],
                },
            },
            "",
        ),
        (
            {
                "took": 6,
                "timed_out": False,
                "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                "hits": {
                    "total": {"value": 2, "relation": "eq"},
                    "max_score": None,
                    "hits": [
                        {
                            "_index": "fluentbit-job_log",
                            "_id": "_kTKspEBC9PZpoJqzxwj",
                            "_score": None,
                            "_source": {
                                "@timestamp": "2024-09-02T12:52:00.984Z",
                                "time": "2024-09-02T12:52:00.984167462Z",
                                "stream": "stderr",
                                "_p": "F",
                                "log": "Executing step 0/1",
                            },
                            "sort": [1725281520984],
                        },
                        {
                            "_index": "fluentbit-job_log",
                            "_id": "xETJspEBC9PZpoJqKRtQ",
                            "_score": None,
                            "_source": {
                                "@timestamp": "2024-09-02T12:50:12.705Z",
                                "time": "2024-09-02T12:50:12.705755718Z",
                                "stream": "stderr",
                                "_p": "F",
                                "log": "Result: 1.3425464",
                            },
                            "sort": [1725281412705],
                        },
                    ],
                },
            },
            """Executing step 0/1
Result: 1.3425464
""",
        ),
        (
            {
                "took": 6,
                "timed_out": False,
                "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                "hits": {
                    "total": {"value": 2, "relation": "eq"},
                    "max_score": None,
                    "hits": [
                        {
                            "_index": "fluentbit-workflow_log",
                            "_id": "_kTKspEBC9PZpoJqzxwj",
                            "_score": None,
                            "_source": {
                                "@timestamp": "2024-09-02T12:52:00.984Z",
                                "time": "2024-09-02T12:52:00.984167462Z",
                                "stream": "stderr",
                                "_p": "F",
                                "log": "2024-09-02 12:52:00,983 | root | MainThread | INFO | Workflow 567bedbc-31d1-4449-8fc6-48af67e04e68 finished.",
                            },
                            "sort": [1725281520984],
                        },
                        {
                            "_index": "fluentbit-workflow_log",
                            "_id": "xETJspEBC9PZpoJqKRtQ",
                            "_score": None,
                            "_source": {
                                "@timestamp": "2024-09-02T12:50:12.705Z",
                                "time": "2024-09-02T12:50:12.705755718Z",
                                "stream": "stderr",
                                "_p": "F",
                                "log": "2024-09-02 12:50:12,705 | root | MainThread | INFO | Publishing step:0.",
                            },
                            "sort": [1725281412705],
                        },
                    ],
                },
            },
            """2024-09-02 12:52:00,983 | root | MainThread | INFO | Workflow 567bedbc-31d1-4449-8fc6-48af67e04e68 finished.
2024-09-02 12:50:12,705 | root | MainThread | INFO | Publishing step:0.
""",
        ),
    ],
)
def test_fetch_logs(opensearch_response, expected_logs):
    """Test OpenSearchLogFetcher.fetch_logs."""
    from reana_workflow_controller.opensearch import OpenSearchLogFetcher

    with patch.object(
        OpenSearch, "search", return_value=opensearch_response
    ) as mock_search:
        opensearch_client = OpenSearch()
        os_fetcher = OpenSearchLogFetcher(opensearch_client)
        logs = os_fetcher.fetch_logs(
            "job_id", "fluentbit-job_log", "kubernetes.labels.job-name.keyword"
        )
    assert logs == expected_logs

    query = {
        "query": {"match": {"kubernetes.labels.job-name.keyword": "job_id"}},
        "sort": [{"@timestamp": {"order": "asc"}}],
    }

    mock_search.assert_called_once_with(
        index="fluentbit-job_log", body=query, size=5000, timeout=5
    )


def test_fetch_logs_error():
    """Test OpenSearchLogFetcher.fetch_logs with error."""
    from reana_workflow_controller.opensearch import OpenSearchLogFetcher

    with patch.object(
        OpenSearch, "search", side_effect=Exception("error")
    ) as mock_search:
        opensearch_client = OpenSearch()
        os_fetcher = OpenSearchLogFetcher(opensearch_client)
        logs = os_fetcher.fetch_logs(
            "job_id", "fluentbit-job_log", "kubernetes.labels.job-name.keyword"
        )
    assert logs is None

    query = {
        "query": {"match": {"kubernetes.labels.job-name.keyword": "job_id"}},
        "sort": [{"@timestamp": {"order": "asc"}}],
    }

    mock_search.assert_called_once_with(
        index="fluentbit-job_log", body=query, size=5000, timeout=5
    )


def test_include_opensearch_disabled():
    """Test OpenSearchLogFetcher inclusion when OpenSearch is disabled (default)."""
    from reana_workflow_controller.opensearch import build_opensearch_log_fetcher

    assert build_opensearch_log_fetcher() is None


def test_include_opensearch_enabled():
    """Test OpenSearchLogFetcher inclusion when OpenSearch is enabled."""
    with patch("reana_workflow_controller.opensearch.REANA_OPENSEARCH_ENABLED", True):
        from reana_workflow_controller.opensearch import build_opensearch_log_fetcher

        assert build_opensearch_log_fetcher() is not None
