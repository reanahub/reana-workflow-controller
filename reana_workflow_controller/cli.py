# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller command line interface."""

import logging

import click
from reana_commons.config import REANA_LOG_FORMAT, REANA_LOG_LEVEL

from reana_workflow_controller.consumer import JobStatusConsumer


@click.command("consume-job-queue")
def consume_job_queue():
    """Consumes job queue and updates job status."""
    logging.basicConfig(level=REANA_LOG_LEVEL, format=REANA_LOG_FORMAT)
    consumer = JobStatusConsumer()
    consumer.run()
