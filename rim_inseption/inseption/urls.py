
from django.urls import path
from . import views



   


urlpatterns = [
    
    path("schedule/", views.list_schedules),
    path("schedule/create/", views.create_schedule),
    path("schedule/create-immediately/", views.create_schedule_immediately),
    path("schedule/delete/<int:schedule_id>/", views.delete_schedule),
    path('schedule/update-immediately/<int:schedule_id>/', views.update_schedule, name='update_schedule'),
    path("schedule/<int:schedule_id>/inspections/", views.InspectionListCreateView.as_view())
    
]
