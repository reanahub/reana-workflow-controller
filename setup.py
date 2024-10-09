# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Workflow-Controller."""

from __future__ import absolute_import, print_function

import os
import re

from setuptools import find_packages, setup

readme = open("README.md").read()
history = open("CHANGELOG.md").read()

extras_require = {
    "debug": [
        "wdb",
        "ipdb",
        "Flask-DebugToolbar",
    ],
    "docs": [
        "myst-parser",
        "Sphinx>=1.5.1",
        "sphinx-rtd-theme>=0.1.9",
        "sphinxcontrib-httpdomain>=1.5.0",
        "sphinxcontrib-openapi>=0.8.0",
        "sphinxcontrib-redoc>=1.5.1",
    ],
    "tests": [
        "pytest-reana>=0.95.0a4,<0.96.0",
    ],
}

extras_require["all"] = []
for key, reqs in extras_require.items():
    if ":" == key[0]:
        continue
    extras_require["all"].extend(reqs)

install_requires = [
    "Flask>=2.1.1,<2.3.0",  # same upper pin as invenio-base/reana-server
    "Werkzeug>=2.1.0,<2.3.0",  # same upper pin as invenio-base
    "gitpython>=2.1",
    "jsonpickle>=0.9.6",
    "marshmallow>2.13.0,<3.0.0",  # same upper pin as reana-server
    "opensearch-py>=2.7.0,<2.8.0",
    "packaging>=18.0",
    "reana-commons[kubernetes] @ git+https://github.com/reanahub/reana-commons.git@0.95.0a4",
    "reana-db>=0.95.0a4,<0.96.0",
    "requests>=2.25.0",
    "sqlalchemy-utils>=0.31.0",
    "uwsgi-tools>=1.1.1",
    "uWSGI>=2.0.17",
    "uwsgitop>=0.10",
    "webargs>=6.1.0,<7.0.0",
]

packages = find_packages()


# Get the version string. Cannot be done with import!
with open(os.path.join("reana_workflow_controller", "version.py"), "rt") as f:
    version = re.search(r'__version__\s*=\s*"(?P<version>.*)"\n', f.read()).group(
        "version"
    )

setup(
    name="reana-workflow-controller",
    version=version,
    description=__doc__,
    long_description=readme + "\n\n" + history,
    long_description_content_type="text/markdown",
    author="REANA",
    author_email="info@reana.io",
    url="https://github.com/reanahub/reana-workflow-controller",
    packages=[
        "reana_workflow_controller",
    ],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        "flask.commands": [
            "consume-job-queue = reana_workflow_controller." "cli:consume_job_queue",
        ]
    },
    python_requires=">=3.8",
    extras_require=extras_require,
    install_requires=install_requires,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
