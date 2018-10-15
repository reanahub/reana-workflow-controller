# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

FROM python:3.6

RUN apt-get update && \
    apt-get install -y vim-tiny && \
    pip install --upgrade pip

COPY CHANGES.rst README.rst setup.py /code/
COPY reana_workflow_controller/version.py /code/reana_workflow_controller/
WORKDIR /code
RUN pip install --no-cache-dir requirements-builder && \
    requirements-builder -e all -l pypi setup.py | pip install --no-cache-dir -r /dev/stdin && \
    pip uninstall -y requirements-builder

COPY . /code

# Debug off by default
ARG DEBUG=false
RUN if [ "${DEBUG}" = "true" ]; then pip install -r requirements-dev.txt; pip install -e .; else pip install .; fi;

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

