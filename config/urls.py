from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from program import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='timetable_index', http_method_names=['post', 'options']), name='logout'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.txt',
        subject_template_name='registration/password_reset_subject.txt'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
    path('organize/', views.organize_index, name='organize_index'),
    path('procgen/', views.procgen_index, name='procgen_index'),
    path('procgen/<int:year>/', views.procgen, name='procgen'),
    path('procgen/<int:year>/<str:program_code>/pdf/', views.proceedings_pdf, name='proceedings_pdf'),
    path('organize/move/', views.move_presentation, name='move_presentation'),
    path('organize/presentation/<int:presentation_id>/edit/', views.edit_presentation, name='edit_presentation'),
    path('organize/session/<int:session_id>/edit/', views.edit_session, name='edit_session'),
    path('organize/session/<int:session_id>/chairs/', views.edit_session_chairs, name='edit_session_chairs'),
    path('organize/<int:year>/reorder-sessions/', views.reorder_sessions, name='reorder_sessions'),
    path('organize/<int:year>/import-program/', views.import_program_excel, name='import_program_excel'),
    path('organize/<int:year>/import-abstract/', views.import_abstract_excel, name='import_abstract_excel'),
    path('organize/<int:year>/export-program/', views.export_program_excel, name='export_program_excel'),
    path('organize/<int:year>/export-program-json/', views.export_program_json, name='export_program_json'),
    path('organize/<int:year>/export-program-pdf/', views.export_program_pdf, name='export_program_pdf'),
    path('organize/legacy-sessions/', views.organize_legacy, name='organize_legacy'),
    path('organize/<int:year>/', views.organize, name='organize'),
    path('organize/<int:year>/publication/', views.set_timetable_publication, name='set_timetable_publication'),
    path('organize/<int:year>/session/', views.create_session, name='create_session'),
    path('organize/<int:year>/move-session-time/', views.move_session_time, name='move_session_time'),
    path('timetable/<int:year>/', views.timetable, name='timetable_legacy'),
    path('<int:year>/web_publish/<str:program_code>.pdf', views.published_proceedings_pdf, name='published_proceedings_pdf'),
    path('<int:year>/', views.timetable, name='timetable'),
    path('', views.timetable_index, name='timetable_index'),
]
