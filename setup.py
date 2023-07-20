# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Workflow-Controller."""

from __future__ import absolute_import, print_function

import os
import re

from setuptools import find_packages, setup

readme = open("README.rst").read()
history = open("CHANGES.rst").read()

tests_require = [
    "pytest-reana>=0.9.1a1,<0.10.0",
]

extras_require = {
    "debug": [
        "wdb",
        "ipdb",
        "Flask-DebugToolbar",
    ],
    "docs": [
        "Sphinx>=1.5.1",
        "sphinx-rtd-theme>=0.1.9",
        "sphinxcontrib-httpdomain>=1.5.0",
        "sphinxcontrib-openapi>=0.8.0",
        "sphinxcontrib-redoc>=1.5.1",
    ],
    "tests": tests_require,
}

extras_require["all"] = []
for key, reqs in extras_require.items():
    if ":" == key[0]:
        continue
    extras_require["all"].extend(reqs)

setup_requires = [
    "pytest-runner>=2.7",
]

install_requires = [
    "Flask>=2.1.1,<2.2.0",
    "Werkzeug>=2.1.0",
    "gitpython>=2.1",
    "jsonpickle>=0.9.6",
    "marshmallow>2.13.0,<=2.20.1",
    "packaging>=18.0",
    "reana-commons[kubernetes]>=0.9.3a4,<0.10.0",
    "reana-db>=0.9.1,<0.10.0",
    "requests==2.25.0",
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
    extras_require=extras_require,
    install_requires=install_requires,
    setup_requires=setup_requires,
    tests_require=tests_require,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
