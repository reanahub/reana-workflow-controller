# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Use Ubuntu LTS base image
FROM docker.io/library/ubuntu:20.04

# Use default answers in installation commands
ENV DEBIAN_FRONTEND=noninteractive

# Use distutils provided by the standard Python library instead of the vendored one in
# setuptools, so that editable installations are stored in the right directory.
# See https://github.com/pypa/setuptools/issues/3301
ENV SETUPTOOLS_USE_DISTUTILS=stdlib

# Prepare list of Python dependencies
COPY requirements.txt /code/

# Install all system and Python dependencies in one go
# hadolint ignore=DL3008,DL3013
RUN apt-get update -y && \
    apt-get install --no-install-recommends -y \
      gcc \
      git \
      libpcre3 \
      libpcre3-dev \
      libpython3.8 \
      python3-pip \
      python3.8 \
      python3.8-dev \
      vim-tiny && \
    pip install --no-cache-dir --upgrade pip setuptools && \
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
RUN if [ "${DEBUG}" -gt 0 ]; then pip --no-cache-dir install -e ".[debug]"; else pip install --no-cache-dir .; fi;

# Are we building with locally-checked-out shared modules?
# hadolint ignore=SC2102
RUN if test -e modules/reana-commons; then pip install --no-cache-dir -e modules/reana-commons[kubernetes] --upgrade; fi
RUN if test -e modules/reana-db; then pip install --no-cache-dir -e modules/reana-db --upgrade; fi

# Check for any broken Python dependencies
RUN pip check

# Set useful environment variables
ARG UWSGI_BUFFER_SIZE=8192
ARG UWSGI_MAX_FD=1048576
ARG UWSGI_PROCESSES=2
ARG UWSGI_THREADS=2
ENV FLASK_APP=reana_workflow_controller/app.py \
    PYTHONPATH=/workdir \
    TERM=xterm \
    UWSGI_BUFFER_SIZE=${UWSGI_BUFFER_SIZE:-8192} \
    UWSGI_MAX_FD=${UWSGI_MAX_FD:-1048576} \
    UWSGI_PROCESSES=${UWSGI_PROCESSES:-2} \
    UWSGI_THREADS=${UWSGI_THREADS:-2}

# Expose ports to clients
EXPOSE 5000

# Run server
# exec is used to make sure signals are propagated to uwsgi,
# while also allowing shell expansion
# hadolint ignore=DL3025
CMD exec uwsgi \
    --buffer-size ${UWSGI_BUFFER_SIZE} \
    --die-on-term \
    --hook-master-start "unix_signal:2 gracefully_kill_them_all" \
    --hook-master-start "unix_signal:15 gracefully_kill_them_all" \
    --enable-threads \
    --http-socket 0.0.0.0:5000 \
    --master \
    --max-fd ${UWSGI_MAX_FD} \
    --module reana_workflow_controller.app:app \
    --need-app \
    --processes ${UWSGI_PROCESSES} \
    --single-interpreter \
    --stats /tmp/stats.socket \
    --threads ${UWSGI_THREADS} \
    --vacuum \
    --wsgi-disable-file-wrapper
