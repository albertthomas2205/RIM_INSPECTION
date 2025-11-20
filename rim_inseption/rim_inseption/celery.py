from __future__ import absolute_import
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rim_inseption.settings")

app = Celery("rim_inseption")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
