from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from .models import Resident, Household, ServiceRequest, Payment, Complaint, ServiceType, Purok, AuditLog, RequestPurpose, UserProfile


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "usable_password", "password1", "password2"),
            },
        ),
    )

@admin.register(Purok)
class PurokAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    
@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ('house_number', 'street', 'purok', 'head')
    search_fields = ('house_number', 'street', 'purok')


@admin.register(Resident)
class ResidentAdmin(admin.ModelAdmin):
    list_display = ('last_name', 'first_name', 'gender', 'voter_status', 'created_at')
    search_fields = ('last_name', 'first_name')
    list_filter = ('gender', 'voter_status')


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'voter_fee', 'non_voter_fee')
    search_fields = ('name',)


@admin.register(RequestPurpose)
class RequestPurposeAdmin(admin.ModelAdmin):
    list_display = ("name", "requires_details", "is_active", "sort_order")
    list_filter = ("is_active", "requires_details")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ('resident', 'service_type','fee', 'status', 'request_date')
    list_filter = ('service_type', 'status')
    search_fields = ('resident__last_name',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'service_request', 'amount', 'payment_date')
    search_fields = ('receipt_number',)


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("title", "resident", "status", "date_filed")
    list_filter = ("status",)
    search_fields = ("title", "resident__last_name")

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "model_name", "target_id", "ip_address")
    list_filter = ("action", "model_name")
    search_fields = ("user__username", "description")
    readonly_fields = (
        "timestamp",
        "user",
        "action",
        "model_name",
        "description",
        "target_id",
        "before_data",
        "after_data",
        "ip_address",
        "user_agent",
        "request_path",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "resident", "first_name", "last_name", "birth_date", "address", "is_verified", "is_auto_matched", "created_at")
    list_filter = ("is_verified", "is_auto_matched")
    search_fields = ("user__username", "first_name", "last_name", "resident__first_name", "resident__last_name")
