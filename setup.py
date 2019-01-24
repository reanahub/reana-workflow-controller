# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Workflow-Controller."""

from __future__ import absolute_import, print_function

import os
import re

from setuptools import find_packages, setup

readme = open('README.rst').read()
history = open('CHANGES.rst').read()

tests_require = [
    'apispec>=0.21.0',
    'check-manifest>=0.25',
    'coverage>=4.0',
    'isort>=4.2.15',
    'pydocstyle>=1.0.0',
    'pytest-cache>=1.0',
    'pytest-cov>=1.8.0',
    'pytest-pep8>=1.0.6',
    'pytest>=3.8.0,<4.0.0',
    'swagger_spec_validator>=2.1.0',
    'pytest-reana>=0.5.0.dev20181203',
]

extras_require = {
    'docs': [
        'Sphinx>=1.4.4',
        'sphinx-rtd-theme>=0.1.9',
        'sphinxcontrib-httpdomain>=1.5.0',
        'sphinxcontrib-openapi>=0.3.0',
        'sphinxcontrib-redoc>=1.5.1',
    ],
    'tests': tests_require,
}

extras_require['all'] = []
for key, reqs in extras_require.items():
    if ':' == key[0]:
        continue
    extras_require['all'].extend(reqs)

setup_requires = [
    'pytest-runner>=2.7',
]

install_requires = [
    'celery>=4.1.0,<4.3',
    'Flask-SQLAlchemy>=2.2',
    'Flask>=0.12',
    'fs>=2.0',
    'jsonpickle>=0.9.6',
    'kubernetes>=6.0.0',
    'marshmallow>=2.13',
    'packaging>=18.0',
    'reana-commons>=0.5.0.dev20190125,<0.6.0[kubernetes]',
    'reana-db>=0.5.0.dev20190125,<0.6.0',
    'requests==2.20.0',
    'sqlalchemy-utils>=0.31.0',
    'uwsgi-tools>=1.1.1',
    'uWSGI>=2.0.17',
    'uwsgitop>=0.10',
]

packages = find_packages()


# Get the version string. Cannot be done with import!
with open(os.path.join('reana_workflow_controller', 'version.py'), 'rt') as f:
    version = re.search(
        '__version__\s*=\s*"(?P<version>.*)"\n',
        f.read()
    ).group('version')

setup(
    name='reana-workflow-controller',
    version=version,
    description=__doc__,
    long_description=readme + '\n\n' + history,
    author='REANA',
    author_email='info@reana.io',
    url='https://github.com/reanahub/reana-workflow-controller',
    packages=['reana_workflow_controller', ],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'flask.commands': [
            'consume-job-queue = reana_workflow_controller.'
            'cli:consume_job_queue',
        ]
    },
    extras_require=extras_require,
    install_requires=install_requires,
    setup_requires=setup_requires,
    tests_require=tests_require,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
