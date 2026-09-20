from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import path
from program import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('organize/', views.organize_index, name='organize_index'),
    path('organize/move/', views.move_presentation, name='move_presentation'),
    path('organize/presentation/<int:presentation_id>/edit/', views.edit_presentation, name='edit_presentation'),
    path('organize/session/<int:session_id>/chairs/', views.edit_session_chairs, name='edit_session_chairs'),
    path('organize/<int:year>/reorder-sessions/', views.reorder_sessions, name='reorder_sessions'),
    path('organize/<int:year>/import-program/', views.import_program_excel, name='import_program_excel'),
    path('organize/<int:year>/import-abstract/', views.import_abstract_excel, name='import_abstract_excel'),
    path('organize/<int:year>/export-program/', views.export_program_excel, name='export_program_excel'),
    path('organize/legacy-sessions/', views.organize_legacy, name='organize_legacy'),
    path('organize/<int:year>/', views.organize, name='organize'),
    path('organize/<int:year>/session/', views.create_session, name='create_session'),
    path('organize/<int:year>/move-session-time/', views.move_session_time, name='move_session_time'),
    path('timetable/<int:year>/excel/', views.timetable_excel, name='timetable_excel'),
    path('timetable/<int:year>/', views.timetable, name='timetable_legacy'),
    path('<int:year>/', views.timetable, name='timetable'),
    path('', views.timetable_index, name='timetable_index'),
]
