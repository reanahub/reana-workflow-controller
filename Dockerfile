# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

FROM python:3.6-slim

RUN apt-get update && \
    apt-get install -y \
      gcc \
      vim-tiny && \
    pip install --upgrade pip

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y git

COPY CHANGES.rst README.rst setup.py /code/
COPY reana_workflow_controller/version.py /code/reana_workflow_controller/

WORKDIR /code
RUN pip install requirements-builder && \
    requirements-builder -l pypi setup.py | pip install -r /dev/stdin && \
    pip uninstall -y requirements-builder

COPY . /code

# Debug off by default
ARG DEBUG=0
RUN if [ "${DEBUG}" -gt 0 ]; then pip install -r requirements-dev.txt; pip install -e .; else pip install .; fi;

# Building with locally-checked-out shared modules?
RUN if test -e modules/reana-commons; then pip install modules/reana-commons --upgrade; fi
RUN if test -e modules/reana-db; then pip install modules/reana-db --upgrade; fi

# Check if there are broken requirements
RUN pip check

EXPOSE 5000
ENV FLASK_APP reana_workflow_controller/app.py

ARG UWSGI_PROCESSES=2
ENV UWSGI_PROCESSES ${UWSGI_PROCESSES:-2}
ARG UWSGI_THREADS=2
ENV UWSGI_THREADS ${UWSGI_THREADS:-2}
ENV TERM=xterm
ENV PYTHONPATH=/workdir

CMD uwsgi --module reana_workflow_controller.app:app \
    --http-socket 0.0.0.0:5000 --master \
    --processes ${UWSGI_PROCESSES} --threads ${UWSGI_THREADS} \
    --stats /tmp/stats.socket \
    --wsgi-disable-file-wrapper
