
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from residents import views
from django.contrib.auth import views as auth_views
from django.urls import path, re_path, reverse_lazy
from django.contrib.auth.views import LogoutView
from residents.forms import ResidentPasswordResetForm
from residents.views import (
    role_redirect, 
    dashboard, 
    secretary_dashboard, 
    treasurer_dashboard, 
    staff_dashboard, 
    resident_list, 
    add_resident
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', role_redirect, name='role_redirect'),
    path('captain/', dashboard, name='captain_dashboard'),
    path('secretary/', secretary_dashboard, name='secretary_dashboard'),
    path('treasurer/', treasurer_dashboard, name='treasurer_dashboard'),
    path('staff/', staff_dashboard, name='staff_dashboard'),

    path('residents/', resident_list, name='resident_list'),
    path('resident/<int:resident_id>/', views.resident_profile, name='resident_profile'),
    path('residents/add/', add_resident, name='add_resident'),
    path("resident/<int:resident_id>/edit/", views.edit_resident, name="edit_resident"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("audit-logs/", views.audit_logs, name="audit_logs"),
    path("residents/scan-id/", views.scan_resident_id, name="scan_resident_id"),
    
    path("create_service_request/<int:resident_id>/", views.create_service_request, name="create_service_request"),
    path(
    "document/<int:request_id>/",
    views.generate_document,
    name="generate_document"
),
    path(
    "document/<int:request_id>/print-release/",
    views.print_and_release_document,
    name="print_and_release_document"
),
    path(
    "service-requests/",
    views.service_requests,
    name="service_requests"
),
    path(
    "service-requests/<int:request_id>/",
    views.service_request_detail,
    name="service_request_detail"
),
    path(
    "service-request/<int:request_id>/update-status/",
    views.update_service_request_status,
    name="update_service_request_status"
),

    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            form_class=ResidentPasswordResetForm,
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
            success_url=reverse_lazy('password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'password-reset-confirm/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'password-reset-complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.resident_register, name='resident_register'),
    path('about/', views.about_barangay, name='about_barangay'),
    path('portal/pending-verification/', views.portal_pending_verification, name='portal_pending_verification'),
    path('portal/service-request/', views.portal_create_service_request, name='portal_create_service_request'),
    path('portal/service-request/<slug:service_slug>/', views.portal_service_request_type, name='portal_service_request_type'),
    path('portal/my-profile/', views.portal_my_profile, name='portal_my_profile'),
    path('portal/notifications/', views.resident_notifications, name='resident_notifications'),
    path('portal/notifications/<int:notification_id>/open/', views.open_notification, name='open_notification'),
    path('portal/notifications/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('secretary/pending-verifications/', views.pending_verifications, name='pending_verifications'),
    path('secretary/pending-verifications/<int:profile_id>/review/', views.review_pending_verification, name='review_pending_verification'),

    path("payments/", views.payment_list, name="payment_list"),
    path("record-payment/<int:request_id>/", views.record_payment, name="record_payment"),
    

    path("household/<int:pk>/", views.household_detail, name="household_detail"),
    path("household/<int:household_id>/add-resident/",
        views.add_resident_to_household,
        name="add_resident_to_household"),
    path("household/<int:household_id>/set-head/<int:resident_id>/",
        views.set_household_head,
        name="set_household_head"),
    path("household/remove-member/<int:resident_id>/",
        views.remove_from_household,
        name="remove_from_household"),
    path("household/add/", views.add_household, name="add_household"),
    path("household/quick-add/", views.quick_add_household, name="quick_add_household"),
    path("households/", views.household_list, name="household_list"),

    path("complaints/", views.complaint_list, name="complaint_list"),
    path("complaints/file/", views.file_complaint, name="file_complaint"),
    path("complaints/<int:complaint_id>/", views.complaint_detail, name="complaint_detail"),
    path("complaints/<int:complaint_id>/update/", views.update_complaint_status, name="update_complaint_status"),
    path("complaints/<int:complaint_id>/schedule/", views.schedule_complaint_hearing, name="schedule_complaint_hearing"),
    path("complaints/<int:complaint_id>/resident-schedule-response/", views.respond_to_complaint_schedule, name="respond_to_complaint_schedule"),
    path("complaints/<int:complaint_id>/withdraw/", views.withdraw_complaint, name="withdraw_complaint"),

    path("export/residents/", views.export_residents_csv, name="export_residents"),
    path("export/payments/", views.export_payments_csv, name="export_payments"),
    path("export/households/", views.export_households_csv, name="export_households"),
    path("export/complaints/", views.export_complaints_csv, name="export_complaints"),
    path("export/summary/", views.export_barangay_summary_csv, name="export_summary"),
]

if settings.MEDIA_URL:
    media_prefix = settings.MEDIA_URL.lstrip("/").rstrip("/")
    urlpatterns += [
        re_path(rf"^{media_prefix}/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
