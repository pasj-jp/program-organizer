from django.contrib import admin
from django.urls import path
from program import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('organize/', views.organize_index, name='organize_index'),
    path('organize/move/', views.move_presentation, name='move_presentation'),
    path('organize/presentation/<int:presentation_id>/edit/', views.edit_presentation, name='edit_presentation'),
    path('organize/<str:abbreviation>/reorder-sessions/', views.reorder_sessions, name='reorder_sessions'),
    path('organize/legacy-sessions/', views.organize_legacy, name='organize_legacy'),
    path('organize/<str:abbreviation>/', views.organize, name='organize'),
    path('organize/<str:abbreviation>/session/', views.create_session, name='create_session'),
    path('timetable/<str:abbreviation>/move/', views.move_session_time, name='move_session_time'),
    path('timetable/<str:abbreviation>/excel/', views.timetable_excel, name='timetable_excel'),
    path('timetable/<str:abbreviation>/', views.timetable, name='timetable'),
    path('', views.timetable_index, name='timetable_index'),
]
