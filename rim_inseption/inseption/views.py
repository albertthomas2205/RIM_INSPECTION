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
from rest_framework.generics import ListCreateAPIView


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

    # ---- TIME PARSING ----
    def parse_time(t):
        try:
            return datetime.strptime(t, "%H:%M").time()
        except ValueError:
            return datetime.strptime(t, "%H:%M:%S").time()

    scheduled_time = parse_time(time)
    scheduled_date = datetime.strptime(date, "%Y-%m-%d").date()

    # ---- COMPUTE 3-MINUTE END TIME ----
    new_start_dt = datetime.combine(scheduled_date, scheduled_time)
    new_end_dt = new_start_dt + timedelta(minutes=3)
    new_end_time = new_end_dt.time()

    # ---- OVERLAP CHECK ----
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

    # ---- SAVE SCHEDULE with UPDATED 3-MIN END TIME ----
    data = request.data.copy()
    data["end_time"] = new_end_time  # <<<<<< CRITICAL FIX

    serializer = ScheduleSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    schedule = serializer.save()

    # ---- CELERY TASKS ----
    start_datetime = timezone.make_aware(
        datetime.combine(schedule.scheduled_date, schedule.scheduled_time)
    )
    end_datetime = timezone.make_aware(
        datetime.combine(schedule.scheduled_date, schedule.end_time)
    )

    set_status_processing.apply_async(args=[schedule.id], eta=start_datetime)
    set_status_completed.apply_async(args=[schedule.id], eta=end_datetime)

    # ---- SUCCESS RESPONSE ----
    return Response(
        {
            "status": 201,
            "message": "Schedule created successfully",
            "success": True,
            "data": serializer.data
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["POST"])
def create_schedule_immediately(request):
    location = request.data.get("location")

    # ---- REQUIRED FIELD VALIDATION ----
    if not location:
        return Response(
            {
                "status": 400,
                "message": "Missing required field: location",
                "success": False,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---- CURRENT IST TIME ----
    now = timezone.localtime()  # IST time
    rounded_now = now.replace(second=0, microsecond=0)

    scheduled_date = rounded_now.date()
    scheduled_time = rounded_now.time()

    # ---- END TIME = +1 hour (rounded) ----
    new_end_dt = rounded_now + timedelta(minutes=3)
    end_time = new_end_dt.replace(second=0, microsecond=0).time()

    # ---- OVERLAP CHECK ----
    overlapping = Schedule.objects.filter(
        location=location,
        scheduled_date=scheduled_date,
        scheduled_time__lt=end_time,
        end_time__gt=scheduled_time
    ).exists()

    if overlapping:
        return Response(
            {
                "status": 400,
                "message": "A schedule already exists for this time slot.",
                "success": False
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ---- SAVE SCHEDULE ----
    schedule = Schedule.objects.create(
        location=location,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        end_time=end_time,
        status="processing"  # start immediately
    )

    # ---- CELERY TASKS ----
    start_datetime = rounded_now  # run now
    end_datetime = new_end_dt     # finish after 1 hour (IST)

    set_status_processing.apply_async(args=[schedule.id], eta=start_datetime)
    set_status_completed.apply_async(args=[schedule.id], eta=end_datetime)

    # ---- RESPONSE ----
    return Response(
        {
            "status": 201,
            "message": "Schedule created and started immediately",
            "success": True,
            "data": {
                "id": schedule.id,
                "location": schedule.location,
                "scheduled_date": str(schedule.scheduled_date),
                "scheduled_time": str(schedule.scheduled_time),
                "end_time": str(schedule.end_time),
                "status": schedule.status
            }
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["PUT"])
def update_schedule(request, schedule_id):

    # 1️⃣ GET SCHEDULE
    try:
        schedule = Schedule.objects.get(id=schedule_id, is_canceled=False)
    except Schedule.DoesNotExist:
        return Response(
            {"status": 404, "message": "Schedule not found", "success": False},
            status=status.HTTP_404_NOT_FOUND
        )

    # Optional: allow location update
    location = request.data.get("location", schedule.location)

    # 2️⃣ GET CURRENT IST TIME (Django already returns IST if TIME_ZONE is set)
    now = timezone.localtime()  # ensures IST even if system/DB is UTC
    rounded_now = now.replace(second=0, microsecond=0)
    new_scheduled_date = rounded_now.date()
    new_scheduled_time = rounded_now.time()

    # 3️⃣ END TIME = +1 hour
    # new_end_dt = now + timedelta(hours=1)
    new_end_dt = now + timedelta(minutes=3)
    new_end_time = new_end_dt.time()

    # 4️⃣ OVERLAP CHECK
    overlapping = Schedule.objects.filter(
        location=location,
        scheduled_date=new_scheduled_date,
        scheduled_time__lt=new_end_time,
        end_time__gt=new_scheduled_time
    ).exclude(id=schedule_id).exists()

    if overlapping:
        return Response(
            {
                "status": 400,
                "message": "Time slot already booked at this location",
                "success": False
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # 5️⃣ UPDATE THE SCHEDULE
    schedule.location = location
    schedule.scheduled_date = new_scheduled_date
    schedule.scheduled_time = new_scheduled_time
    schedule.end_time = new_end_time
    schedule.status = "processing"  # start immediately
    schedule.save()

    # 6️⃣ CELERY TASKS (Correct IST scheduling)
    start_datetime = timezone.localtime()          # IST now
    end_datetime = new_end_dt                      # IST + 1 hour

    set_status_processing.apply_async(args=[schedule.id], eta=start_datetime)
    set_status_completed.apply_async(args=[schedule.id], eta=end_datetime)

    # 7️⃣ RESPONSE
    return Response(
        {
            "status": 200,
            "message": "Schedule updated with current IST date/time and started",
            "success": True,
            "data": {
                "id": schedule.id,
                "location": schedule.location,
                "scheduled_date": str(schedule.scheduled_date),
                "scheduled_time": str(schedule.scheduled_time),
                "end_time": str(schedule.end_time),
                "status": schedule.status,
            }
        },
        status=status.HTTP_200_OK
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


@swagger_auto_schema(
    method="post",
    request_body=InspectionSerializer,
    responses={201: "Schedule created"}
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
# class InspectionListCreateView(APIView):

#     parser_classes = [MultiPartParser, FormParser, JSONParser]

#     def post(self, request, schedule_id):

#         data = request.data.copy()
#         data["schedule"] = schedule_id  # attach FK

#         serializer = InspectionSerializer(data=data)
#         if serializer.is_valid():
#             serializer.save()
#             return Response(
#                 {
#                     "success": True,
#                     "message": "Inspection created successfully",
#                     "data": serializer.data
#                 },
#                 status=status.HTTP_201_CREATED
#             )

#         return Response(
#             {
#                 "success": False,
#                 "message": "Validation failed",
#                 "errors": serializer.errors
#             },
#             status=status.HTTP_400_BAD_REQUEST
#         )





# class InspectionListCreateView(ListCreateAPIView):
#     serializer_class = InspectionSerializer
#     parser_classes = [MultiPartParser, FormParser, JSONParser]

#     def get_queryset(self):
#         return Inspection.objects.filter(schedule=self.kwargs["schedule_id"])

#     def perform_create(self, serializer):
#         schedule_id = self.kwargs["schedule_id"]
#         serializer.save(schedule_id=schedule_id)



class InspectionListCreateView(ListCreateAPIView):
    serializer_class = InspectionSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return Inspection.objects.filter(schedule=self.kwargs["schedule_id"])

    def perform_create(self, serializer):
        schedule_id = self.kwargs["schedule_id"]
        serializer.save(schedule_id=schedule_id)

    # ✅ Custom success response
    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)

        return Response({
            "success": True,
            "message": "Inspection created successfully",
            "inspection": response.data
        }, status=status.HTTP_201_CREATED)

    
        # ---------- GET CUSTOM RESPONSE ----------
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            "success": True,
            "message": "Inspections retrieved successfully",
            "inspections": serializer.data
        }, status=status.HTTP_200_OK)

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



class StartSpeakView(APIView):
    def get(self, request):
        return Response({
            "success": True,
            "message": "Speak started successfully",
            "data": {
                "speak": True
            }
        })


class StopSpeakView(APIView):
    def get(self, request):
        return Response({
            "success": True,
            "message": "Speak stopped successfully",
            "data": {
                "speak": False
            }
        })
