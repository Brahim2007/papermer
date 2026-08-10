from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PaperMetrics.settings')

app = Celery('PaperMetrics')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# Namespace='CELERY' means all celery-related configuration keys
# should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Explicitly set broker and result backend from Django settings if not using namespace
# app.conf.broker_url = settings.CELERY_BROKER_URL
# app.conf.result_backend = settings.CELERY_RESULT_BACKEND

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))
