# views.py
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import datetime, timedelta
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .models import Schedule, Inspection
from .serializers import ScheduleSerializer, InspectionSerializer
from .tasks import set_status_processing, set_status_completed
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi


@swagger_auto_schema(
    method="post",
    request_body=ScheduleSerializer,
    responses={201: "Schedule created"}
)

@api_view(["POST"])
def create_schedule(request):
    location = request.data.get("location")
    date = request.data.get("scheduled_date")
    time = request.data.get("scheduled_time")

    # ---- REQUIRED FIELD VALIDATION ----
    missing_fields = []
    if not location:
        missing_fields.append("location")
    if not date:
        missing_fields.append("scheduled_date")
    if not time:
        missing_fields.append("scheduled_time")

    if missing_fields:
        return Response(
            {
                "status": 400,
                "message": f"Missing required fields: {', '.join(missing_fields)}",
                "success": False,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---- TIME PARSING FIX ----
    def parse_time(t):
        try:
            return datetime.strptime(t, "%H:%M").time()
        except ValueError:
            return datetime.strptime(t, "%H:%M:%S").time()

    scheduled_time = parse_time(time)
    scheduled_date = datetime.strptime(date, "%Y-%m-%d").date()

    # Compute END TIME
    new_start_dt = datetime.combine(scheduled_date, scheduled_time)
    new_end_dt = new_start_dt + timedelta(hours=1)
    new_end_time = new_end_dt.time()

    # Overlap check
    overlapping = Schedule.objects.filter(
        location=location,
        scheduled_date=scheduled_date,
        scheduled_time__lt=new_end_time,
        end_time__gt=scheduled_time
    ).exists()

    if overlapping:
        return Response(
            {
                "status": 400,
                "message": "Time slot already booked for this location",
                "success": False
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Save schedule
    serializer = ScheduleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    schedule = serializer.save()

    # Celery tasks
    start_datetime = timezone.make_aware(
        datetime.combine(schedule.scheduled_date, schedule.scheduled_time)
    )
    end_datetime = timezone.make_aware(
        datetime.combine(schedule.scheduled_date, schedule.end_time)
    )

    set_status_processing.apply_async(args=[schedule.id], eta=start_datetime)
    set_status_completed.apply_async(args=[schedule.id], eta=end_datetime)

    return Response(
        {
            "status": 201,
            "message": "Schedule created successfully",
            "success": True,
            "data": serializer.data
        },
        status=status.HTTP_201_CREATED
    )


# -----------------------------------
# DELETE SCHEDULE
# -----------------------------------
@api_view(["DELETE"])
def delete_schedule(request, schedule_id):

    # Check if schedule exists
    try:
        schedule = Schedule.objects.get(id=schedule_id, is_canceled=False)
    except Schedule.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Schedule not found",
            },
            status=status.HTTP_404_NOT_FOUND
        )

    # Prevent deleting completed schedules
    if schedule.status == "completed":
        return Response(
            {
                "success": False,
                "message": "Completed schedule cannot be deleted",
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Soft delete
    schedule.is_canceled = True
    schedule.save()

    return Response(
        {
            "success": True,
            "message": "Schedule deleted successfully",
        },
        status=status.HTTP_200_OK
    )


# -----------------------------------
# CREATE INSPECTION (Simple)
# -----------------------------------
@api_view(["POST"])
def create_inspection(request):
    serializer = InspectionSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Inspection created successfully",
                "inspections": serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    return Response(
        {
            "success": False,
            "message": "Validation failed",
            "errors": serializer.errors,
        },
        status=status.HTTP_400_BAD_REQUEST
    )


# -----------------------------------
# LIST SCHEDULES
# -----------------------------------
@api_view(["GET"])
def list_schedules(request):
    schedules = Schedule.objects.filter(is_canceled=False).order_by("-id")
    serializer = ScheduleSerializer(schedules, many=True)

    return Response(
        {
            "success": True,
            "message": "Schedules fetched successfully",
            "schedules": serializer.data,
        },
        status=status.HTTP_200_OK
    )


# -----------------------------------
# CREATE INSPECTION WITH SCHEDULE ID
# -----------------------------------
class InspectionListCreateView(APIView):

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, schedule_id):

        data = request.data.copy()
        data["schedule"] = schedule_id  # attach FK

        serializer = InspectionSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "success": True,
                    "message": "Inspection created successfully",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )


# -----------------------------------
# CREATE INSPECTION (Standalone)
# -----------------------------------
class InspectionCreateView(APIView):

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        serializer = InspectionSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "success": True,
                    "message": "Inspection created successfully",
                    "inspections": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )

