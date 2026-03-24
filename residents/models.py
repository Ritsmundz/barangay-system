from datetime import date, timezone

from django.db import models
from django.contrib.auth.models import User

# Create your models here.

#PUROK
#PUROK
#PUROK
class Purok(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name
    
#HOUSEHOLD
#HOUSEHOLD
#HOUSEHOLD
class Household(models.Model):
    house_number = models.CharField(max_length=20)
    street = models.CharField(max_length=100)
    purok = models.ForeignKey(Purok, on_delete=models.SET_NULL, null=True, blank=True, related_name="households"    )

    head = models.ForeignKey(
        'Resident',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='household_head'
    )

    def __str__(self):
        return f"{self.house_number} {self.street} - {self.purok}"

#RESIDENTS
#RESIDENTS
#RESIDENTS
class Resident(models.Model):
     
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
    ]
    STATUS_CHOICES = [
        ("Alive", "Alive"),
        ("Deceased", "Deceased"),
        ("Moved", "Moved Out"),
    ]
    EDUCATIONAL_ATTAINMENT_CHOICES = [
        ("", "---------"),
        ("No Formal Education", "No Formal Education"),
        ("Elementary", "Elementary"),
        ("High School", "High School"),
        ("Vocational", "Vocational"),
        ("College", "College"),
        ("Postgraduate", "Postgraduate"),
    ]

    household = models.ForeignKey(
        Household, 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100)
    suffix = models.CharField(max_length=20, blank=True, null=True)

    birth_date = models.DateField()
    place_of_birth = models.CharField(max_length=150, blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    civil_status = models.CharField(max_length=20)
    nationality = models.CharField(max_length=100, blank=True, null=True)
    religion = models.CharField(max_length=100, blank=True, null=True)
    occupation = models.CharField(max_length=120, blank=True, null=True)
    educational_attainment = models.CharField(
        max_length=50,
        choices=EDUCATIONAL_ATTAINMENT_CHOICES,
        blank=True,
        default="",
    )
    pwd = models.BooleanField(default=False)
    indigenous = models.BooleanField(default=False)
    solo_parent = models.BooleanField(default=False)
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Alive"
    )

    contact_number = models.CharField(max_length=15, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    precinct = models.CharField(max_length=50, blank=True, null=True)

    voter_status = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def age(self):
        if not self.birth_date:
            return None

        today = date.today()

        age = today.year - self.birth_date.year - (
            (today.month, today.day) <
            (self.birth_date.month, self.birth_date.day)
        )

        return age
    
    @property
    def age_group(self):

        age = self.age

        if age is None:
            return "Unknown"

        if age <= 12:
            return "Child"

        elif age <= 17:
            return "Youth"

        elif age <= 59:
            return "Adult"

        else:
            return "Senior Citizen"

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    resident = models.OneToOneField(
        Resident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profile",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    birth_date = models.DateField()
    is_verified = models.BooleanField(default=False)
    is_auto_matched = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} ({'Verified' if self.is_verified else 'Pending'})"

#SERVICE TYPE
#SERVICE TYPE
#SERVICE TYPE
class ServiceType(models.Model):

    name = models.CharField(max_length=100)
    fee = models.DecimalField(max_digits=8, decimal_places=2)
    voter_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    non_voter_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    def __str__(self):
        return self.name


class RequestPurpose(models.Model):
    name = models.CharField(max_length=100, unique=True)
    requires_details = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name
    
#SERVICE REQUEST
#SERVICE REQUEST
#SERVICE REQUEST
from datetime import date
from django.utils import timezone
class ServiceRequest(models.Model):
    PURPOSE_CHOICES = [
        ("Barangay Clearance", "Barangay Clearance"),
        ("Local Employment", "Local Employment"),
        ("Bank Requirement", "Bank Requirement"),
        ("Postal ID", "Postal ID"),
        ("Police Clearance", "Police Clearance"),
        ("NBI Clearance", "NBI Clearance"),
        ("Senior Citizen ID", "Senior Citizen ID"),
        ("PSA", "PSA"),
        ("First Time Job Seeker", "First Time Job Seeker"),
        ("Other", "Other (state)"),
    ]

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
        ('Approved', 'Approved'),
        ('Released', 'Released'),
        ('Rejected', 'Rejected'),
    ]

    resident = models.ForeignKey(
        Resident,
        on_delete=models.CASCADE,
        related_name='service_requests'
    )

    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.CASCADE,
        related_name="requests"
    )

    purpose_option = models.ForeignKey(
        RequestPurpose,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests",
    )

    purpose = models.TextField(blank=True, null=True)
    purpose_for = models.CharField(max_length=100, choices=PURPOSE_CHOICES, blank=True, null=True)
    purpose_other = models.CharField(max_length=255, blank=True, null=True)

    emergency_contact_name = models.CharField(max_length=150, blank=True, null=True)
    emergency_contact_address = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact_number = models.CharField(max_length=30, blank=True, null=True)

    residency_since = models.DateField(blank=True, null=True)

    fee = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Pending'
    )

    document_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True
    )

    request_date = models.DateTimeField(auto_now_add=True)

    processed_date = models.DateTimeField(blank=True, null=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_requests"
    )

    remarks = models.TextField(blank=True, null=True)

    clearance_number = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.service_type} - {self.resident}"

    @property
    def purpose_display(self):
        if self.purpose_option:
            if self.purpose_option.requires_details and self.purpose_other:
                return self.purpose_other
            return self.purpose_option.name
        if self.purpose_for == "Other" and self.purpose_other:
            return self.purpose_other
        if self.purpose_for:
            return self.purpose_for
        return self.purpose or "-"

    def save(self, *args, **kwargs):

        # SNAPSHOT FEE
        if not self.fee:
            if self.resident and self.resident.voter_status:
                self.fee = self.service_type.voter_fee
            else:
                self.fee = self.service_type.non_voter_fee

            # AUTO SET PROCESSED DATE WHEN RELEASED
        if self.status == "Released" and not self.processed_date:
            self.processed_date = timezone.now()

        # GENERATE DOCUMENT NUMBER
        if not self.document_number:

            year = date.today().year
            prefix = self.service_type.name[:3].upper()

            last_request = ServiceRequest.objects.filter(
                document_number__startswith=f"{prefix}-{year}"
            ).order_by("id").last()

            if last_request:
                last_number = int(last_request.document_number.split("-")[-1])
                new_number = last_number + 1
            else:
                new_number = 1

            self.document_number = f"{prefix}-{year}-{new_number:04d}"

        super().save(*args, **kwargs)

#PAYMENT
#PAYMENT
#PAYMENT
from datetime import date

class Payment(models.Model):

    service_request = models.OneToOneField(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="payment"
    )

    receipt_number = models.CharField(  
        max_length=50,
        unique=True,
        blank=True
    )

    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_received"

    )


    amount = models.DecimalField(max_digits=10, decimal_places=2)

    payment_date = models.DateTimeField(auto_now_add=True)

    collected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_collected"
    )

    def save(self, *args, **kwargs):

        if not self.receipt_number:

            year = date.today().year

            last_payment = Payment.objects.filter(
                receipt_number__startswith=f"RCPT-{year}"
            ).order_by("id").last()

            if last_payment:
                last_number = int(last_payment.receipt_number.split("-")[-1])
                new_number = last_number + 1
            else:
                new_number = 1

            self.receipt_number = f"RCPT-{year}-{new_number:04d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return self.receipt_number


# COMPLAINT SYSTEM
# COMPLAINT SYSTEM
# COMPLAINT SYSTEM

class Complaint(models.Model):

    STATUS_CHOICES = [
    ('Pending', 'Pending'),
    ('Under Investigation', 'Under Investigation'),
    ('For Mediation', 'For Mediation'),
    ('Resolved', 'Resolved'),
    ('Dismissed', 'Dismissed'),
]

    resident = models.ForeignKey(
        Resident,
        on_delete=models.CASCADE,
        related_name="complaints"
    )

    title = models.CharField(max_length=200)

    description = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    filed_by = models.ForeignKey(
    User,
    on_delete=models.SET_NULL,
    null=True,
    blank=True
)

    date_filed = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.resident}"
    
#AUDIT LOGS
#AUDIT LOGS
#AUDIT LOGS
class AuditLog(models.Model):

    ACTION_CHOICES = [
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("LOGIN", "Login"),
        ("LOGOUT", "Logout"),
        ("LOGIN_FAILED", "Login Failed"),
        ("EXPORT", "Export"),
        ("PRINT", "Print"),
        ("ROLE_CHANGE", "Role Change"),
        ("PERMISSION_CHANGE", "Permission Change"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)

    model_name = models.CharField(max_length=100)

    description = models.TextField()

    target_id = models.CharField(max_length=100, null=True, blank=True)

    before_data = models.JSONField(null=True, blank=True)

    after_data = models.JSONField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    user_agent = models.CharField(max_length=255, blank=True)

    request_path = models.CharField(max_length=255, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["action"]),
            models.Index(fields=["model_name"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.model_name}"
