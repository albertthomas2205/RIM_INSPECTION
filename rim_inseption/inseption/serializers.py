# serializers.py

from rest_framework import serializers
from .models import Schedule, Inspection

class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schedule
        fields = "__all__"


class InspectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inspection
        fields = "__all__"
