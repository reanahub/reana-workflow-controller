# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Workflow Controller command line interface."""

import logging

import click

from reana_workflow_controller.consumer import JobStatusConsumer


@click.command('consume-job-queue')
def consume_job_queue():
    """Consumes job queue and updates job status."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(threadName)s - %(levelname)s: %(message)s'
    )
    consumer = JobStatusConsumer()
    consumer.consume()
