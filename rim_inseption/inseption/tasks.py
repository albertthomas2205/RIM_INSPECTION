# tasks.py

from celery import shared_task
from django.utils import timezone
from .models import Schedule


@shared_task
def set_status_processing(schedule_id):
    try:
        schedule = Schedule.objects.get(id=schedule_id)
        schedule.status = "processing"
        schedule.save()
    except Schedule.DoesNotExist:
        pass


@shared_task
def set_status_completed(schedule_id):
    try:
        schedule = Schedule.objects.get(id=schedule_id)
        schedule.status = "completed"
        schedule.save()
    except Schedule.DoesNotExist:
        pass
