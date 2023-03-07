# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Use Ubuntu LTS base image
FROM ubuntu:20.04

# Use default answers in installation commands
ENV DEBIAN_FRONTEND=noninteractive

# Prepare list of Python dependencies
COPY requirements.txt /code/

# Install all system and Python dependencies in one go
# hadolint ignore=DL3008, DL3013
RUN apt-get update -y && \
    apt-get install --no-install-recommends -y \
      gcc \
      git \
      libpython3.8 \
      python3.8 \
      python3.8-dev \
      python3-pip \
      vim-tiny && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /code/requirements.txt && \
    apt-get remove -y \
      gcc \
      python3.8-dev && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy cluster component source code
WORKDIR /code
COPY . /code

# Are we debugging?
ARG DEBUG=0
RUN if [ "${DEBUG}" -gt 0 ]; then pip install -e ".[debug]"; else pip install .; fi;

# Are we building with locally-checked-out shared modules?
# hadolint ignore=SC2102
RUN if test -e modules/reana-commons; then pip install -e modules/reana-commons[kubernetes] --upgrade; fi
RUN if test -e modules/reana-db; then pip install -e modules/reana-db --upgrade; fi

# Check for any broken Python dependencies
RUN pip check

# Set useful environment variables
ARG UWSGI_PROCESSES=2
ARG UWSGI_THREADS=2
ENV FLASK_APP=reana_workflow_controller/app.py \
    PYTHONPATH=/workdir \
    TERM=xterm \
    UWSGI_PROCESSES=${UWSGI_PROCESSES:-2} \
    UWSGI_THREADS=${UWSGI_THREADS:-2}

# Expose ports to clients
EXPOSE 5000

# Run server
# hadolint ignore=DL3025
CMD uwsgi \
    --http-socket 0.0.0.0:5000 \
    --master \
    --max-fd 1048576 \
    --module reana_workflow_controller.app:app \
    --processes ${UWSGI_PROCESSES} \
    --stats /tmp/stats.socket \
    --threads ${UWSGI_THREADS} \
    --wsgi-disable-file-wrapper
