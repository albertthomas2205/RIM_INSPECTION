
from django.urls import path
from . import views



   


urlpatterns = [
    
    path("schedule/create/", views.create_schedule),
    path("schedule/", views.list_schedules),
    path("schedule/delete/<int:schedule_id>/", views.delete_schedule),
    path("schedule/<int:schedule_id>/inspections/", views.InspectionListCreateView.as_view())
    
]
