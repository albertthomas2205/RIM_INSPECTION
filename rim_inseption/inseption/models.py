from django.db import models
from datetime import timedelta, datetime

# Create your models here.


class Schedule(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
    ]

    location = models.CharField(max_length=150)
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    is_canceled = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="scheduled")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Auto set end_time = scheduled_time + 1 hour
        if self.scheduled_time and not self.end_time:
            dt = datetime.combine(self.scheduled_date, self.scheduled_time)
            self.end_time = (dt + timedelta(hours=1)).time()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Schedule {self.id} at {self.location}"


class Inspection(models.Model):
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="inspections")
    rim_id = models.CharField(max_length=50,unique=True)

    image = models.ImageField(upload_to="rim_photos/", null=True, blank=True)
    is_defect = models.BooleanField(default=False)

    inspected_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(null=True, blank=True) 
    class Meta:
        unique_together = ("schedule", "rim_id")
    def __str__(self):
        return f"Inspection {self.rim_id} -> Schedule {self.schedule.id}"
