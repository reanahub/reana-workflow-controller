from __future__ import absolute_import

import json
import os
from celery import Celery
import requests


celery = Celery('tasks',
                broker='amqp://test:1234@workflow-broker//')

celery.conf.update(CELERY_ACCEPT_CONTENT=['json'],
                   CELERY_TASK_SERIALIZER='json')


fibonacci = celery.signature('tasks.fibonacci')
run_yadage_workflow = celery.signature('tasks.run_yadage_workflow')
