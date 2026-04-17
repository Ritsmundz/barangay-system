from calendar import month
from datetime import date, timedelta, datetime
import csv
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from functools import wraps
import logging
from django.http import HttpResponse
from django.http import JsonResponse
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotAllowed
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.db.models.functions import ExtractMonth
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import Group, User
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.text import slugify
from .models import Resident, Household, ServiceRequest, ServiceRequestAttachment, Payment, Complaint, ServiceType, Purok, AuditLog, RequestPurpose, UserProfile, Notification
from .forms import (
    ResidentForm,
    HouseholdForm,
    ComplaintForm,
    ClearanceRequestForm,
    ResidentPortalRegistrationForm,
    ResidentVerificationCreateForm,
    ServiceRequestRequirementsForm,
    ServiceRequestResidentSubmissionForm,
)
from .audit import log_audit_event, snapshot_instance

logger = logging.getLogger(__name__)


def get_secretary_email_recipients():
    return list(
        User.objects.filter(groups__name="Secretary", is_active=True)
        .exclude(email__isnull=True)
        .exclude(email__exact="")
        .values_list("email", flat=True)
        .distinct()
    )


def notify_secretaries_of_pending_registration(request, profile):
    secretary_emails = get_secretary_email_recipients()

    if not secretary_emails:
        return

    resident_name = " ".join(
        part for part in [profile.first_name, profile.last_name] if part
    ).strip() or profile.user.username
    subject = "Pending resident registration verification"
    message = (
        "A new resident registration is waiting for secretary verification.\n\n"
        f"Resident name: {resident_name}\n"
        f"Username: {profile.user.username}\n"
        f"Birth date: {profile.birth_date:%Y-%m-%d}\n"
        f"Address: {profile.address}\n"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=secretary_emails,
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send pending registration notification email.")


def notify_secretaries_of_service_request(service_request):
    secretary_emails = get_secretary_email_recipients()
    if not secretary_emails:
        return

    resident = service_request.resident
    resident_name = " ".join(
        part for part in [resident.first_name, resident.last_name] if part
    ).strip() or str(resident)
    subject = "New resident service request submitted"
    message = (
        "A resident submitted a new service request and it is waiting for secretary review.\n\n"
        f"Resident name: {resident_name}\n"
        f"Service: {service_request.service_type.name}\n"
        f"Reference: {service_request.document_number or service_request.clearance_number or f'Request #{service_request.id}'}\n"
        f"Status: {service_request.status}\n"
        f"Purpose: {service_request.purpose_display}\n"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=secretary_emails,
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            "Failed to send secretary service request notification email for request %s.",
            service_request.id,
        )


def notify_secretaries_of_complaint(complaint):
    secretary_emails = get_secretary_email_recipients()
    if not secretary_emails:
        return

    resident = complaint.resident
    resident_name = " ".join(
        part for part in [resident.first_name, resident.last_name] if part
    ).strip() or str(resident)
    subject = "New resident complaint submitted"
    message = (
        "A resident submitted a new complaint and it is waiting for secretary review.\n\n"
        f"Resident name: {resident_name}\n"
        f"Complaint title: {complaint.title}\n"
        f"Status: {complaint.status}\n"
        f"Description: {complaint.description}\n"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=secretary_emails,
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            "Failed to send secretary complaint notification email for complaint %s.",
            complaint.id,
        )


def notify_resident_registration_decision(profile, *, approved):
    recipient = (profile.user.email or "").strip()
    if not recipient:
        return

    resident_name = " ".join(
        part for part in [profile.first_name, profile.last_name] if part
    ).strip() or profile.user.username

    if approved:
        subject = "Your resident registration has been approved"
        message = (
            f"Hello {resident_name},\n\n"
            "Your resident portal registration has been approved by Barangay Gulod.\n"
            "You can now sign in to your resident account and access the portal services.\n\n"
            "If you did not request this registration, please contact the barangay office.\n"
        )
    else:
        subject = "Your resident registration has been rejected"
        message = (
            f"Hello {resident_name},\n\n"
            "Your resident portal registration was not approved by Barangay Gulod.\n"
            "If you believe this was a mistake or you need to correct your details, "
            "please contact the barangay office before submitting a new request.\n"
        )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            "Failed to send resident registration decision email for profile %s.",
            profile.id,
        )


def about_barangay(request):
    context = {
        "official_name": "Rey Aldrin S. Tolentino",
        "official_title": "Punong Barangay",
        "contact_address": "Villaflor Village, Barangay Gulod, Novaliches, Quezon City",
        "contact_phone": "8-3663-198",
        "contact_email": "teamtolentino@gmail.com",
        "facebook_label": "Facebook",
        "office_hours": "Monday to Friday, 8:00 AM to 5:00 PM",
        "coverage_summary": "Barangay Gulod serves a growing residential community in Novaliches through coordinated local governance, resident support, and digital request handling.",
        "system_summary": "The Barangay Gulod E-Governance System centralizes resident registration, verification, service requests, complaints, and notifications in one online platform.",
        "stats": [
            {"label": "Population", "value": "70,000", "sub": "RBI"},
            {"label": "Households", "value": "14,801", "sub": "PSA 2020"},
            {"label": "Average Household Size", "value": "4.2", "sub": "PSA 2020"},
            {"label": "Registered Voters", "value": "44,239", "sub": "Latest barangay count"},
        ],
        "councilors_left": [
            "Lovely Alphine S. Biglang-Awa",
            "Marlon S. Serrano",
            "Glendale B. Clerigo",
            "Lovely Alphine S. Biglang-Awa",
        ],
        "councilors_right": [
            "Sherill B. Acle",
            "Percival M. Casteltort",
            "Edgar P. Mabalot",
            "Nonito D. Gonzales",
        ],
        "schools": [
            {
                "name": "Rosa L. Susano Elementary School",
                "address": "Quirino Highway, Brgy. Gulod, Novaliches, Quezon City",
            },
            {
                "name": "Jose Maria Panganiban Senior High School",
                "address": "Villaflor Subdivision, Brgy. Gulod, Novaliches, Quezon City",
            },
        ],
    }
    return render(request, "about_barangay.html", context)
SERVICE_REQUEST_PRIMARY_STEPS = [
    "Submitted",
    "Under Review",
    "For Validation",
    "Processing",
    "Ready for Release",
    "Released",
]

SERVICE_REQUEST_OPTIONAL_STATES = [
    "Pending Requirements",
    "On Hold",
    "Rejected",
    "Cancelled",
]

SERVICE_REQUEST_STATUS_TRANSITIONS = {
    "Submitted": ["Under Review", "Cancelled"],
    "Under Review": ["For Validation", "Pending Requirements", "On Hold", "Rejected", "Cancelled"],
    "Pending Requirements": ["Under Review", "Cancelled"],
    "For Validation": ["Processing", "On Hold", "Rejected", "Cancelled"],
    "On Hold": ["For Validation", "Cancelled"],
    "Processing": ["Ready for Release", "On Hold", "Rejected", "Cancelled"],
    "Ready for Release": ["Released", "On Hold", "Cancelled"],
    "Released": [],
    "Rejected": [],
    "Cancelled": [],
}

SERVICE_REQUEST_STATUS_COLORS = {
    "Submitted": "blue",
    "Under Review": "sky",
    "For Validation": "violet",
    "Processing": "teal",
    "Ready for Release": "amber",
    "Released": "green",
    "Pending Requirements": "gold",
    "On Hold": "orange",
    "Rejected": "red",
    "Cancelled": "slate",
}

SERVICE_REQUEST_ESTIMATES = {
    "Submitted": "Usually reviewed within the day.",
    "Under Review": "Usually checked within 1 working day.",
    "For Validation": "Validation usually takes 1 to 2 working days.",
    "Processing": "Document preparation usually takes 1 working day.",
    "Ready for Release": "Ready for pickup once the Secretary confirms release.",
    "Released": "This request has already been claimed.",
    "Pending Requirements": "Waiting for the resident to complete missing information.",
    "On Hold": "Temporarily delayed while verification is being resolved.",
    "Rejected": "This request will not proceed unless resubmitted correctly.",
    "Cancelled": "This request has been closed without release.",
}

COMPLAINT_STATUS_TRANSITIONS = {
    "Submitted": ["Under Review"],
    "Under Review": ["For Scheduling", "Referred"],
    "For Scheduling": ["Scheduled for Hearing", "Referred"],
    "Scheduled for Hearing": ["Ongoing Mediation", "Unresolved"],
    "Ongoing Mediation": ["Resolved / Settled", "Unresolved", "Referred"],
    "Resolved / Settled": [],
    "Unresolved": [],
    "Referred": [],
    "Withdrawn": [],
}

COMPLAINT_STATUS_COLORS = {
    "Submitted": "blue",
    "Under Review": "violet",
    "For Scheduling": "amber",
    "Scheduled for Hearing": "amber",
    "Ongoing Mediation": "orange",
    "Resolved / Settled": "green",
    "Unresolved": "gold",
    "Referred": "red",
    "Withdrawn": "slate",
}

COMPLAINT_SCHEDULE_RESPONSE_COLORS = {
    "Pending Response": "gold",
    "Acknowledged": "green",
    "Needs Reschedule": "amber",
    "Cannot Attend": "red",
}

PORTAL_SERVICE_THEME_MAP = {
    "barangay clearance": {
        "category": "certificates",
        "badge": "BC",
        "card_tone": "blue",
        "description": "Secure a barangay clearance for employment, travel, banking, or other official transactions.",
        "summary": "Commonly used for local applications, travel, and supporting document requirements.",
        "requirements": [
            "Review your resident information before submitting.",
            "Select the exact purpose of the request.",
            "Wait for status updates in your notifications panel.",
        ],
    },
    "indigency": {
        "category": "certificates",
        "badge": "CI",
        "card_tone": "green",
        "description": "Request a certificate of indigency for financial assistance, scholarship, or social support requirements.",
        "summary": "Used to certify financial need for assistance-based applications.",
        "requirements": [
            "Choose the purpose carefully.",
            "If you pick Other, add a clear explanation.",
            "Make sure your resident record is up to date.",
        ],
    },
    "certificate of residency": {
        "category": "certificates",
        "badge": "CR",
        "card_tone": "sky",
        "description": "Request proof that you currently reside in the barangay.",
        "summary": "Useful for school, banking, and address verification requirements.",
        "requirements": [
            "Confirm your household address is correct.",
            "Select the purpose of the document.",
            "Track approval from your resident dashboard.",
        ],
    },
    "barangay id": {
        "category": "identification",
        "badge": "ID",
        "card_tone": "indigo",
        "description": "Apply for a barangay-issued resident ID for local identification purposes.",
        "summary": "Requires an emergency contact before submission.",
        "requirements": [
            "Provide a reachable emergency contact person.",
            "Double-check the emergency contact address and number.",
            "Your resident profile details will be used for the ID record.",
        ],
    },
    "qcid": {
        "category": "identification",
        "badge": "QC",
        "card_tone": "violet",
        "description": "Submit your QCID-related request with the barangay residency information needed for review.",
        "summary": "Requires your residency date in the barangay.",
        "requirements": [
            "Set the date when you started residing in the barangay.",
            "Make sure your personal details match your resident record.",
            "Expect validation before processing starts.",
        ],
    },
    "first time job seeker": {
        "category": "employment",
        "badge": "FT",
        "card_tone": "amber",
        "description": "Request documents supporting first-time job seeker applications and related benefits.",
        "summary": "Ideal for residents applying for work for the first time.",
        "requirements": [
            "Choose Employment or First Time Job Seeker as your purpose.",
            "Review your contact information before submitting.",
            "Check notifications for further verification if needed.",
        ],
    },
    "business clearance": {
        "category": "employment",
        "badge": "BU",
        "card_tone": "rose",
        "description": "Request a barangay business clearance for local permit and registration processing.",
        "summary": "Used to support business registration or renewal requirements.",
        "requirements": [
            "State the reason for the clearance request.",
            "Use your active resident profile details.",
            "Wait for validation and release updates online.",
        ],
    },
}

PORTAL_SERVICE_TONE_STYLES = {
    "blue": {"soft": "#edf4ff", "icon": "#dceaff", "accent": "#2563eb"},
    "green": {"soft": "#eefbf5", "icon": "#d2f5e3", "accent": "#0f9f6e"},
    "sky": {"soft": "#eef8ff", "icon": "#d8eeff", "accent": "#0284c7"},
    "indigo": {"soft": "#eef2ff", "icon": "#dde5ff", "accent": "#4f46e5"},
    "violet": {"soft": "#f5f1ff", "icon": "#e8ddff", "accent": "#7c3aed"},
    "amber": {"soft": "#fff8ea", "icon": "#ffe8bb", "accent": "#d97706"},
    "rose": {"soft": "#fff1f3", "icon": "#ffdce3", "accent": "#e11d48"},
    "slate": {"soft": "#f4f7fb", "icon": "#e3e9f3", "accent": "#475569"},
}

PORTAL_SERVICE_CATALOG = [
    {
        "slug": "barangay-clearance",
        "name": "Barangay Clearance",
        "base_type": "Service Request",
        "category": "certificates",
        "badge": "BC",
        "card_tone": "blue",
        "description": "Get a barangay clearance for job applications, travel, banking, and other official transactions.",
        "summary": "General-purpose barangay clearance request.",
        "requirements": [
            "Choose the exact purpose of the clearance.",
            "Review your resident information before submitting.",
            "Track release updates from the portal.",
        ],
        "purposes": [
            "Local Employment",
            "Abroad Employment",
            "Business Requirement",
            "Bank Requirement",
            "School Requirement",
            "Travel Requirement",
            "Loan Application",
            "Police Clearance Requirement",
            "NBI Clearance Requirement",
            "Other",
        ],
    },
    {
        "slug": "certificate-of-residency",
        "name": "Certificate of Residency",
        "base_type": "Service Request",
        "category": "certificates",
        "badge": "CR",
        "card_tone": "sky",
        "description": "Request proof that you currently live in the barangay for school, ID, or address verification use.",
        "summary": "Used for residency and address verification.",
        "requirements": [
            "Confirm your household address is correct.",
            "Select the reason you need the certificate.",
            "Submit once your resident details are accurate.",
        ],
        "purposes": [
            "Proof of Address",
            "School Requirement",
            "Bank Requirement",
            "ID Application",
            "Utility Application",
            "Employment Requirement",
            "Travel Requirement",
            "Other",
        ],
    },
    {
        "slug": "first-time-job-seeker",
        "name": "First Time Job Seeker",
        "base_type": "Service Request",
        "category": "employment",
        "badge": "FT",
        "card_tone": "amber",
        "description": "Request a supporting barangay certification for first-time job seeker applications and benefits.",
        "summary": "Employment-related request for first-time applicants.",
        "requirements": [
            "Choose a job-seeker related purpose.",
            "Make sure your profile details are updated.",
            "Wait for review and release notices online.",
        ],
        "purposes": [
            "Local Employment",
            "Pre-Employment Requirement",
            "Government ID Application",
            "NBI Clearance Requirement",
            "Police Clearance Requirement",
            "Resume or Job Application Support",
            "Other",
        ],
    },
    {
        "slug": "business-clearance",
        "name": "Business Clearance",
        "base_type": "Service Request",
        "category": "employment",
        "badge": "BU",
        "card_tone": "rose",
        "description": "Request barangay clearance support for business registration, renewal, or permit processing.",
        "summary": "Business-related request for permit and registration use.",
        "requirements": [
            "Select the business-related purpose.",
            "Review resident details linked to the request.",
            "Use the portal to monitor processing status.",
        ],
        "purposes": [
            "New Business Registration",
            "Business Permit Renewal",
            "Mayor's Permit Requirement",
            "BIR Requirement",
            "DTI Requirement",
            "Licensing Requirement",
            "Other",
        ],
    },
    {
        "slug": "barangay-permit",
        "name": "Barangay Permit",
        "base_type": "Service Request",
        "category": "others",
        "badge": "BP",
        "card_tone": "indigo",
        "description": "Submit a permit-related request for activities, events, or local barangay approval needs.",
        "summary": "Permit and approval request page.",
        "requirements": [
            "Choose the reason for the permit request.",
            "Submit only accurate resident information.",
            "Expect review before release or follow-up.",
        ],
        "purposes": [
            "Event Permit",
            "Gathering or Assembly Permit",
            "Construction or Renovation Request",
            "Minor Business Activity",
            "Stall or Booth Permit",
            "Street or Public Space Use",
            "Sound System or Program Permit",
            "Other",
        ],
    },
    {
        "slug": "solo-parent-certificate",
        "name": "Solo Parent Certificate",
        "base_type": "Service Request",
        "category": "certificates",
        "badge": "SP",
        "card_tone": "violet",
        "description": "Request a barangay certification to support solo parent-related records or applications.",
        "summary": "Certificate request for solo parent documentation.",
        "requirements": [
            "Select the purpose that best fits your request.",
            "Double-check your linked resident information.",
            "Monitor the request through portal notifications.",
        ],
        "purposes": [
            "Solo Parent ID Application",
            "Benefit Application",
            "School Requirement",
            "Financial Assistance",
            "Record Verification",
            "Other",
        ],
    },
    {
        "slug": "senior-citizen-certificate",
        "name": "Senior Citizen Certificate",
        "base_type": "Service Request",
        "category": "certificates",
        "badge": "SC",
        "card_tone": "green",
        "description": "Request a barangay certification to support senior citizen-related documentation and applications.",
        "summary": "Certificate request for senior citizen support documents.",
        "requirements": [
            "Use the correct request purpose.",
            "Ensure your birthdate and resident profile are accurate.",
            "Track progress online after submission.",
        ],
        "purposes": [
            "Senior Citizen ID Application",
            "Benefit Application",
            "Pension Requirement",
            "Medical Assistance",
            "Record Verification",
            "Other",
        ],
    },
    {
        "slug": "certificate-of-indigency",
        "name": "Certificate of Indigency",
        "base_type": "Indigency",
        "category": "certificates",
        "badge": "CI",
        "card_tone": "green",
        "description": "Obtain a certificate of indigency for scholarship, financial assistance, medical support, or social aid.",
        "summary": "Indigency certification for assistance-related requirements.",
        "requirements": [
            "Choose the exact assistance purpose.",
            "If you select Other, provide specific details.",
            "Review all resident information before submitting.",
        ],
        "purposes": [
            "Medical Assistance",
            "Hospital Assistance",
            "Burial Assistance",
            "Scholarship Application",
            "Educational Assistance",
            "Financial Assistance",
            "DSWD Requirement",
            "PhilHealth or Social Support",
            "Other",
        ],
    },
    {
        "slug": "medical-assistance",
        "name": "Medical Assistance Certification",
        "base_type": "Indigency",
        "category": "certificates",
        "badge": "MA",
        "card_tone": "rose",
        "description": "Use this page when the indigency certificate will be used for medicine, hospitalization, or medical support.",
        "summary": "Medical-support version of an indigency request.",
        "requirements": [
            "Choose a medical assistance purpose if applicable.",
            "Add details when Other purpose is selected.",
            "Watch for review updates in notifications.",
        ],
        "purposes": [
            "Medicine Assistance",
            "Hospital Admission Support",
            "Laboratory Assistance",
            "Surgical Assistance",
            "Medical Financial Assistance",
            "PhilHealth or Social Support",
            "Other",
        ],
    },
    {
        "slug": "scholarship-assistance",
        "name": "Scholarship Assistance Certification",
        "base_type": "Indigency",
        "category": "employment",
        "badge": "SA",
        "card_tone": "amber",
        "description": "Request an indigency certification for scholarship, school support, or educational assistance needs.",
        "summary": "Education-support version of an indigency request.",
        "requirements": [
            "Choose a scholarship-related purpose.",
            "Check that your profile details are correct.",
            "Add other details only when required.",
        ],
        "purposes": [
            "Scholarship Application",
            "Educational Assistance",
            "Tuition Support",
            "School Financial Assistance",
            "Student Aid Requirement",
            "Other",
        ],
    },
    {
        "slug": "barangay-id",
        "name": "Barangay ID Issuance",
        "base_type": "Barangay ID",
        "category": "identification",
        "badge": "ID",
        "card_tone": "indigo",
        "description": "Apply for a barangay ID as a local proof of identity and residency.",
        "summary": "Identification request with emergency contact requirements.",
        "requirements": [
            "Provide a complete emergency contact record.",
            "Review your address and contact information.",
            "Submit only if your resident profile is correct.",
        ],
        "purposes": [
            "New ID Application",
            "ID Renewal",
            "Replacement for Lost ID",
            "Replacement for Damaged ID",
            "Update of Resident Information",
            "Other",
        ],
    },
    {
        "slug": "solo-parent-id-endorsement",
        "name": "Solo Parent ID Endorsement",
        "base_type": "Barangay ID",
        "category": "identification",
        "badge": "SI",
        "card_tone": "violet",
        "description": "Use this page for an ID-style barangay endorsement flow related to solo parent ID applications.",
        "summary": "ID-related request with emergency contact information.",
        "requirements": [
            "Provide emergency contact details.",
            "Verify your resident profile before submitting.",
            "Expect review before processing begins.",
        ],
        "purposes": [
            "New ID Endorsement",
            "ID Renewal",
            "Replacement for Lost ID",
            "Replacement for Damaged ID",
            "Update of Resident Information",
            "Other",
        ],
    },
    {
        "slug": "qcid-assistance",
        "name": "QCID Assistance",
        "base_type": "QCID",
        "category": "identification",
        "badge": "QC",
        "card_tone": "violet",
        "description": "Request barangay support for QCID processing with your residency information.",
        "summary": "QCID-related request that requires residency date.",
        "requirements": [
            "Provide the date you started living in the barangay.",
            "Make sure your identity details are correct.",
            "Track validation and processing status online.",
        ],
        "purposes": [
            "QCID New Application",
            "QCID Update",
            "QCID Verification",
            "Residency Proof for ID Application",
            "Address Verification",
            "Other",
        ],
    },
    {
        "slug": "proof-of-residency",
        "name": "Proof of Residency for ID",
        "base_type": "QCID",
        "category": "identification",
        "badge": "PR",
        "card_tone": "sky",
        "description": "Submit an ID-related proof of residency request that requires your barangay residency timeline.",
        "summary": "Residency-based request using the QCID workflow.",
        "requirements": [
            "Enter the correct residency start date.",
            "Confirm your household address before submission.",
            "Wait for validation updates from the office.",
        ],
        "purposes": [
            "Residency Proof for ID Application",
            "Address Verification",
            "Supporting Document for Government ID",
            "QCID Requirement",
            "Other",
        ],
    },
]

COMPLAINT_OPEN_STATUSES = [
    "Submitted",
    "Under Review",
    "For Scheduling",
    "Scheduled for Hearing",
    "Ongoing Mediation",
]

COMPLAINT_CLOSED_STATUSES = [
    "Resolved / Settled",
    "Unresolved",
    "Referred",
    "Withdrawn",
]


def get_service_request_allowed_statuses(current_status):
    return SERVICE_REQUEST_STATUS_TRANSITIONS.get(current_status, [])


def get_service_request_progress_status(status):
    if status in SERVICE_REQUEST_PRIMARY_STEPS:
        return status
    if status == "Pending Requirements":
        return "Under Review"
    if status == "On Hold":
        return "For Validation"
    if status in {"Rejected", "Cancelled"}:
        return "Submitted"
    return "Submitted"


def get_service_request_status_history(service_request):
    logs = AuditLog.objects.filter(
        model_name="ServiceRequest",
        target_id=str(service_request.id),
    ).select_related("user").order_by("timestamp")

    history = []
    seen_statuses = set()

    history.append({
        "status": "Submitted",
        "timestamp": service_request.request_date,
        "actor": service_request.created_by,
        "description": "Request submitted by resident.",
    })
    seen_statuses.add("Submitted")

    for log in logs:
        before_status = (log.before_data or {}).get("status")
        after_status = (log.after_data or {}).get("status")
        if not after_status or before_status == after_status:
            continue
        if after_status in seen_statuses and after_status != service_request.status:
            continue
        history.append({
            "status": after_status,
            "timestamp": log.timestamp,
            "actor": log.user,
            "description": log.description,
        })
        seen_statuses.add(after_status)

    history.sort(key=lambda item: item["timestamp"])
    return history


def create_notification(*, user, title, message, category="general", target_url=""):
    if not user:
        return None
    return Notification.objects.create(
        user=user,
        title=title,
        message=message,
        category=category,
        target_url=target_url or "",
    )
def notify_resident_for_service_request(service_request, *, title, message):
    resident_profile = getattr(service_request.resident, "user_profile", None)
    if not resident_profile or not resident_profile.user_id:
        return None

    notification = create_notification(
        user=resident_profile.user,
        title=title,
        message=message,
        category="service_request",
        target_url=f"/service-requests/{service_request.id}/",
    )

    recipient = (resident_profile.user.email or "").strip()
    if recipient:
        resident_name = " ".join(
            part for part in [resident_profile.first_name, resident_profile.last_name] if part
        ).strip() or resident_profile.user.username
        service_name = service_request.service_type.name
        request_reference = service_request.document_number or service_request.clearance_number or f"Request #{service_request.id}"
        email_subject = f"Barangay Gulod Service Request Update: {title}"
        email_message = (
            f"Hello {resident_name},\n\n"
            f"There is an update on your {service_name} request.\n\n"
            f"Reference: {request_reference}\n"
            f"Update: {title}\n"
            f"Details: {message}\n\n"
            "You may also check the same update in your resident portal notifications.\n"
        )
        try:
            send_mail(
                subject=email_subject,
                message=email_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception:
            logger.exception(
                "Failed to send service request notification email for request %s.",
                service_request.id,
            )

    return notification


def notify_resident_for_complaint(complaint, *, title, message):
    resident_profile = getattr(complaint.resident, "user_profile", None)
    if not resident_profile or not resident_profile.user_id:
        return None
    return create_notification(
        user=resident_profile.user,
        title=title,
        message=message,
        category="complaint",
        target_url=f"/complaints/{complaint.id}/",
    )

def is_captain(user):
    return user.groups.filter(name='Captain').exists()

def is_secretary(user):
    return user.groups.filter(name='Secretary').exists()


def is_treasurer(user):
    return user.groups.filter(name='Treasurer').exists()


def is_staff_group_user(user):
    return user.groups.filter(name='Staff').exists()


def is_staff_user(user):
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=["Captain", "Secretary", "Treasurer", "Staff"]).exists()


def is_resident(user):
    return user.groups.filter(name="Resident").exists()


def group_required(test_func):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            if test_func(request.user):
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("You do not have permission to access this page.")
        return _wrapped_view
    return decorator


def get_user_profile(user):
    return UserProfile.objects.filter(user=user).select_related("resident").first()


def normalize_service_name(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def get_portal_service_theme(service_type):
    normalized_name = normalize_service_name(service_type.name)
    theme = PORTAL_SERVICE_THEME_MAP.get(normalized_name, {})
    tone_key = theme.get("card_tone", "slate")
    tone_styles = PORTAL_SERVICE_TONE_STYLES[tone_key]

    category = theme.get("category")
    if not category:
        if "id" in normalized_name:
            category = "identification"
        elif any(keyword in normalized_name for keyword in ("job", "employment", "business")):
            category = "employment"
        else:
            category = "others"

    badge = theme.get("badge")
    if not badge:
        badge = "".join(part[:1].upper() for part in service_type.name.split()[:2]) or "SR"

    return {
        "slug": slugify(service_type.name),
        "category": category,
        "badge": badge,
        "description": theme.get("description", "Submit this service request online and track its processing status from your resident account."),
        "summary": theme.get("summary", "Request processing and release updates will appear in your notifications."),
        "requirements": theme.get("requirements", [
            "Review the resident details shown on the page.",
            "Fill in the required request information.",
            "Submit once all information is complete.",
        ]),
        "soft_color": tone_styles["soft"],
        "icon_color": tone_styles["icon"],
        "accent_color": tone_styles["accent"],
    }


def get_service_type_lookup():
    return {
        service_type.name.lower(): service_type
        for service_type in ServiceType.objects.order_by("name")
    }


def build_portal_service(service_entry, service_type):
    tone_styles = PORTAL_SERVICE_TONE_STYLES[service_entry.get("card_tone", "slate")]
    fee_value = service_type.voter_fee if service_type else 0
    non_voter_fee = service_type.non_voter_fee if service_type else 0
    return {
        "slug": service_entry["slug"],
        "name": service_entry["name"],
        "category": service_entry["category"],
        "badge": service_entry["badge"],
        "description": service_entry["description"],
        "summary": service_entry["summary"],
        "requirements": service_entry["requirements"],
        "purposes": service_entry.get("purposes", []),
        "accent_color": tone_styles["accent"],
        "soft_color": tone_styles["soft"],
        "icon_color": tone_styles["icon"],
        "service_type": service_type,
        "id": service_type.id if service_type else None,
        "base_type_name": service_entry["base_type"],
        "voter_fee": service_type.voter_fee if service_type else 0,
        "non_voter_fee": service_type.non_voter_fee if service_type else 0,
        "default_fee": fee_value or non_voter_fee,
    }


def get_portal_services():
    lookup = get_service_type_lookup()
    services = []
    for entry in PORTAL_SERVICE_CATALOG:
        service_type = lookup.get(entry["base_type"].lower())
        if not service_type:
            continue
        service = build_portal_service(entry, service_type)
        service["rules"] = get_service_request_rules(service_type)
        services.append(service)
    return services


def get_portal_service_by_slug(service_slug):
    for service in get_portal_services():
        if service["slug"] == service_slug:
            return service
    return None


def get_service_request_rules(service_type):
    normalized_name = normalize_service_name(service_type.name)
    requires_purpose = normalized_name in {
        "barangay clearance",
        "certificate of residency",
        "indigency",
        "service request",
        "first time job seeker",
        "business clearance",
        "barangay permit",
        "solo parent id",
    }
    requires_emergency = normalized_name == "barangay id"
    requires_residency = normalized_name in {"qcid", "qc id"}

    return {
        "normalized_name": normalized_name,
        "requires_purpose": requires_purpose,
        "requires_emergency": requires_emergency,
        "requires_residency": requires_residency,
    }


def get_resident_portal_context(request):
    if not is_resident(request.user):
        return None, HttpResponseForbidden("Only resident accounts can access this page.")

    profile = get_user_profile(request.user)
    if not profile:
        messages.error(request, "Resident profile not found. Please register first.")
        return None, redirect("resident_register")

    if not profile.is_verified or not profile.resident:
        messages.error(request, "Your account is still pending verification.")
        return None, redirect("portal_pending_verification")

    return profile, None


def build_service_request_form_context(request, resident, service_types, service_purposes, *, selected_service=None):
    selected_service_type = None
    if selected_service:
        selected_service_type = selected_service.get("service_type") if isinstance(selected_service, dict) else selected_service
    return {
        "resident": resident,
        "service_types": service_types,
        "service_purposes": service_purposes,
        "posted_data": request.POST if request.method == "POST" else None,
        "selected_service": selected_service,
        "selected_service_theme": selected_service if isinstance(selected_service, dict) else (get_portal_service_theme(selected_service) if selected_service else None),
        "selected_service_rules": get_service_request_rules(selected_service_type) if selected_service_type else (get_service_request_rules(selected_service) if selected_service else None),
        "selected_service_purposes": selected_service.get("purposes", []) if isinstance(selected_service, dict) else [],
        "is_portal_service_page": selected_service is not None,
    }


def handle_service_request_submission(request, resident, service_types, service_purposes, *, selected_service=None):
    service_type_id = request.POST.get("service_type")
    purpose_option_id = request.POST.get("purpose_for")
    portal_purpose_choice = (request.POST.get("portal_purpose") or "").strip()
    purpose_other = (request.POST.get("purpose_other") or "").strip()

    selected_service_type = selected_service.get("service_type") if isinstance(selected_service, dict) else selected_service

    if selected_service is not None:
        service_type = selected_service_type
    else:
        if not service_type_id:
            messages.error(request, "Please select a service type.")
            return None, build_service_request_form_context(
                request,
                resident,
                service_types,
                service_purposes,
                selected_service=selected_service,
            )
        service_type = get_object_or_404(ServiceType, id=service_type_id)

    rules = get_service_request_rules(service_type)
    purpose_option = None
    purpose_text = None

    if rules["requires_purpose"]:
        if isinstance(selected_service, dict):
            available_purposes = selected_service.get("purposes", [])
            if not portal_purpose_choice or portal_purpose_choice not in available_purposes:
                messages.error(request, "Please select a purpose.")
                return None, build_service_request_form_context(
                    request,
                    resident,
                    service_types,
                    service_purposes,
                    selected_service=selected_service,
                )
            if portal_purpose_choice == "Other":
                if not purpose_other:
                    messages.error(request, "Please specify the purpose details.")
                    return None, build_service_request_form_context(
                        request,
                        resident,
                        service_types,
                        service_purposes,
                        selected_service=selected_service,
                    )
                purpose_text = purpose_other
            else:
                purpose_text = portal_purpose_choice
        else:
            if not purpose_option_id:
                messages.error(request, "Please select a purpose.")
                return None, build_service_request_form_context(
                    request,
                    resident,
                    service_types,
                    service_purposes,
                    selected_service=selected_service,
                )
            purpose_option = get_object_or_404(RequestPurpose, id=purpose_option_id, is_active=True)
            if purpose_option.requires_details and not purpose_other:
                messages.error(request, "Please specify the purpose details.")
                return None, build_service_request_form_context(
                    request,
                    resident,
                    service_types,
                    service_purposes,
                    selected_service=selected_service,
                )
            purpose_text = purpose_other if purpose_option.requires_details else purpose_option.name
    elif selected_service is not None:
        purpose_text = selected_service["name"]

    emergency_contact_name = (request.POST.get("emergency_contact_name") or "").strip() or None
    emergency_contact_address = (request.POST.get("emergency_contact_address") or "").strip() or None
    emergency_contact_number = (request.POST.get("emergency_contact_number") or "").strip() or None
    residency_since = (request.POST.get("residency_since") or None)

    if rules["requires_emergency"]:
        if not emergency_contact_name or not emergency_contact_address or not emergency_contact_number:
            messages.error(request, "Please complete all emergency contact fields for Barangay ID.")
            return None, build_service_request_form_context(
                request,
                resident,
                service_types,
                service_purposes,
                selected_service=selected_service,
            )

    if rules["requires_residency"] and not residency_since:
        messages.error(request, "Please provide residency date for QCID.")
        return None, build_service_request_form_context(
            request,
            resident,
            service_types,
            service_purposes,
            selected_service=selected_service,
        )

    service = ServiceRequest.objects.create(
        resident=resident,
        service_type=service_type,
        purpose_option=purpose_option,
        purpose=purpose_text,
        purpose_for=(
            purpose_option.name if purpose_option else
            portal_purpose_choice if isinstance(selected_service, dict) and portal_purpose_choice else
            selected_service["name"] if selected_service is not None else None
        ),
        purpose_other=(purpose_other or None) if purpose_option else None,
        emergency_contact_name=emergency_contact_name if rules["requires_emergency"] else None,
        emergency_contact_address=emergency_contact_address if rules["requires_emergency"] else None,
        emergency_contact_number=emergency_contact_number if rules["requires_emergency"] else None,
        residency_since=residency_since if rules["requires_residency"] else None,
        status="Submitted",
        created_by=request.user,
    )

    log_audit_event(
        action="CREATE",
        model_name="ServiceRequest",
        description=f"Created {service_type} request for {resident}",
        user=request.user,
        target_id=service.id,
        after_data=snapshot_instance(service),
        request=request,
    )

    year = service.request_date.year
    service.clearance_number = f"{year}-{service.id:04d}"
    service.save()

    notify_resident_for_service_request(
        service,
        title="Request Submitted",
        message=f"Your {service.service_type.name} request has been submitted successfully.",
    )
    notify_secretaries_of_service_request(service)

    return service, None


def logout_view(request):
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])

    try:
        auth_logout(request)
    except Exception:
        logger.exception("Logout failed; forcing session cleanup.")
        if hasattr(request, "session"):
            request.session.flush()
        request.user = AnonymousUser()

    return redirect("login")


def _extract_resident_data_from_ocr(text):
    cleaned = re.sub(r"\r", "", text or "")
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    upper_text = cleaned.upper()
    data = {}

    def find_value_after_label(label_pattern):
        for ln in lines:
            match = re.search(label_pattern + r"\s*[:\-]?\s*(.+)$", ln, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def normalize_date(raw):
        if not raw:
            return None
        raw = raw.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            return raw
        m = re.match(r"^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$", raw)
        if m:
            yyyy, mm, dd = m.groups()
            return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
        m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$", raw)
        if m:
            mm, dd, yyyy = m.groups()
            return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2})$", raw)
        if m:
            mm, dd, yy = m.groups()
            yyyy = int(yy) + (2000 if int(yy) < 50 else 1900)
            return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"

        month_map = {
            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
            "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
        }
        m = re.match(r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2})\s+(\d{4})$", raw.upper())
        if m:
            mon, dd, yyyy = m.groups()
            mm = month_map[mon[:3]]
            return f"{yyyy}-{mm:02d}-{int(dd):02d}"
        return None

    first_name = find_value_after_label(r"first\s*name")
    middle_name = find_value_after_label(r"middle\s*name")
    last_name = find_value_after_label(r"last\s*name")
    suffix = find_value_after_label(r"suffix")
    birth_place = find_value_after_label(r"(birth\s*place|birthplace)")
    civil_status = find_value_after_label(r"civil\s*status")
    precinct = find_value_after_label(r"(precinct|precint)")
    nationality = find_value_after_label(r"nationality")
    religion = find_value_after_label(r"religion")

    sex = find_value_after_label(r"(sex|gender)")
    if sex:
        sex = sex.strip().capitalize()
        if sex not in ("Male", "Female"):
            sex = None
    if not sex:
        if re.search(r"\bSEX\b.*\bMALE\b", upper_text) or re.search(r"\bGENDER\b.*\bMALE\b", upper_text):
            sex = "Male"
        elif re.search(r"\bSEX\b.*\bFEMALE\b", upper_text) or re.search(r"\bGENDER\b.*\bFEMALE\b", upper_text):
            sex = "Female"
        elif re.search(r"\bSEX\b\s*[:\-]?\s*M\b", upper_text):
            sex = "Male"
        elif re.search(r"\bSEX\b\s*[:\-]?\s*F\b", upper_text):
            sex = "Female"

    if not civil_status:
        if "SINGLE" in upper_text:
            civil_status = "Single"
        elif "MARRIED" in upper_text:
            civil_status = "Married"
        elif "WIDOWED" in upper_text:
            civil_status = "Widowed"
        elif "SEPARATED" in upper_text:
            civil_status = "Separated"
        elif "DIVORCED" in upper_text:
            civil_status = "Divorced"

    raw_birth_date = (
        find_value_after_label(r"(birth\s*date|date\s*of\s*birth|birthdate)")
        or next((ln for ln in lines if re.search(r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4}", ln)), None)
    )
    if raw_birth_date and ":" in raw_birth_date:
        raw_birth_date = raw_birth_date.split(":", 1)[-1].strip()
    birth_date = normalize_date(raw_birth_date)
    if not birth_date:
        m = re.search(r"\b(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})\b", cleaned)
        if m:
            birth_date = normalize_date(m.group(1))
    if not birth_date:
        m = re.search(r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b", cleaned)
        if m:
            birth_date = normalize_date(m.group(1))
    if not birth_date:
        m = re.search(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{1,2}\s+\d{4}\b", upper_text)
        if m:
            birth_date = normalize_date(m.group(0))

    if not (first_name and last_name):
        full_name_line = find_value_after_label(r"name")
        if full_name_line and not (first_name and last_name):
            parts = [p for p in re.split(r"\s+", full_name_line) if p]
            if len(parts) >= 2:
                if not first_name:
                    first_name = parts[0]
                if not last_name:
                    last_name = parts[-1]
                if len(parts) > 2 and not middle_name:
                    middle_name = " ".join(parts[1:-1])
    if not (first_name and last_name):
        candidate_lines = []
        noise_words = {"REPUBLIC", "PHILIPPINES", "ADDRESS", "BIRTH", "SEX", "GENDER", "CIVIL", "STATUS", "NATIONALITY", "ID", "CARD"}
        for ln in lines[:8]:
            if re.search(r"\d", ln):
                continue
            tokens = [t for t in re.split(r"\s+", ln.upper()) if t]
            if len(tokens) < 2:
                continue
            if any(tok in noise_words for tok in tokens):
                continue
            candidate_lines.append(ln)

        if candidate_lines:
            raw_name = max(candidate_lines, key=len)
            if "," in raw_name:
                left, right = raw_name.split(",", 1)
                last_name = last_name or left.strip().title()
                right_parts = [p for p in re.split(r"\s+", right.strip()) if p]
                if right_parts:
                    first_name = first_name or right_parts[0].title()
                if len(right_parts) > 1:
                    middle_name = middle_name or " ".join(p.title() for p in right_parts[1:])
            else:
                name_parts = [p for p in re.split(r"\s+", raw_name.strip()) if p]
                if len(name_parts) >= 2:
                    first_name = first_name or name_parts[0].title()
                    last_name = last_name or name_parts[-1].title()
                    if len(name_parts) > 2:
                        middle_name = middle_name or " ".join(p.title() for p in name_parts[1:-1])

    if first_name:
        data["first_name"] = first_name
    if middle_name:
        data["middle_name"] = middle_name
    if last_name:
        data["last_name"] = last_name
    if suffix:
        data["suffix"] = suffix
    if birth_date:
        data["birth_date"] = birth_date
    if birth_place:
        data["place_of_birth"] = birth_place
    if sex:
        data["gender"] = sex
    if civil_status:
        data["civil_status"] = civil_status
    if precinct:
        data["precinct"] = precinct
    if nationality:
        data["nationality"] = nationality
    if religion:
        data["religion"] = religion

    qcid_data = _extract_qcid_data_from_ocr(cleaned)
    for key, value in qcid_data.items():
        if value:
            data[key] = value

    data = _normalize_extracted_name_fields(data, cleaned)
    data = _remove_address_like_name_noise(data)

    return data


def _try_decode_qr_payloads(image):
    payloads = []
    qr_detected = False
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"payloads": payloads, "qr_detected": qr_detected}

    try:
        rgb = image.convert("RGB")
        arr = np.array(rgb)
        detector = cv2.QRCodeDetector()

        # Try multiple variants to improve decode reliability for cropped QR images.
        variants = [arr]
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        variants.append(cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB))
        variants.append(cv2.cvtColor(cv2.equalizeHist(gray), cv2.COLOR_GRAY2RGB))
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(cv2.cvtColor(bw, cv2.COLOR_GRAY2RGB))
        h, w = gray.shape[:2]
        up2 = cv2.resize(arr, (max(1, w * 2), max(1, h * 2)), interpolation=cv2.INTER_CUBIC)
        variants.append(up2)

        for variant in variants:
            bgr = cv2.cvtColor(variant, cv2.COLOR_RGB2BGR)

            detected, points = detector.detect(bgr)
            if detected and points is not None:
                qr_detected = True

            data, points_single, _ = detector.detectAndDecode(bgr)
            if points_single is not None:
                qr_detected = True
            if data and data not in payloads:
                payloads.append(data)

            ok, decoded_info, points_multi, _ = detector.detectAndDecodeMulti(bgr)
            if points_multi is not None:
                qr_detected = True
            if ok and decoded_info:
                for d in decoded_info:
                    if d and d not in payloads:
                        payloads.append(d)
    except Exception:
        return {"payloads": payloads, "qr_detected": qr_detected}
    return {"payloads": payloads, "qr_detected": qr_detected}


def _extract_resident_data_from_qr_payload(payload):
    if not payload:
        return {}

    data = {}
    raw = payload.strip()

    # 1) JSON payload
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            for src, dst in {
                "first_name": "first_name",
                "middle_name": "middle_name",
                "last_name": "last_name",
                "suffix": "suffix",
                "birth_date": "birth_date",
                "birthdate": "birth_date",
                "gender": "gender",
                "sex": "gender",
                "civil_status": "civil_status",
                "place_of_birth": "place_of_birth",
                "birth_place": "place_of_birth",
                "precinct": "precinct",
                "precint": "precinct",
                "nationality": "nationality",
                "religion": "religion",
            }.items():
                val = obj.get(src)
                if val:
                    data[dst] = str(val).strip()
    except Exception:
        pass

    # 2) URL query payload
    if not data and ("?" in raw and ("http://" in raw.lower() or "https://" in raw.lower())):
        try:
            parsed = urlparse(raw)
            q = parse_qs(parsed.query)
            for src, dst in {
                "first_name": "first_name",
                "middle_name": "middle_name",
                "last_name": "last_name",
                "suffix": "suffix",
                "birth_date": "birth_date",
                "birthdate": "birth_date",
                "gender": "gender",
                "sex": "gender",
                "civil_status": "civil_status",
                "place_of_birth": "place_of_birth",
                "birth_place": "place_of_birth",
                "precinct": "precinct",
                "precint": "precinct",
                "nationality": "nationality",
                "religion": "religion",
            }.items():
                if src in q and q[src]:
                    data[dst] = q[src][0].strip()
        except Exception:
            pass

    # 3) key:value text payload
    if not data and "|" in raw:
        # 3) Pipe-delimited QCID-like payload
        # Example:
        # LAST, FIRST MIDDLE|IDNO|CIVIL_CODE|YYMMDD|SEX|...|ISSUE_YYMMDD|
        parts = [p.strip() for p in raw.split("|")]
        if parts and "," in parts[0]:
            name_part = parts[0]
            last, rest = [p.strip() for p in name_part.split(",", 1)]
            name_tokens = [t.strip(". ") for t in rest.split() if t.strip(". ")]
            if last:
                data["last_name"] = last.title()
            if name_tokens:
                # QCID case: "JOHN RICHMOND P." -> first_name="John Richmond", middle_name="P"
                if len(name_tokens) >= 2 and len(name_tokens[-1]) <= 2:
                    data["first_name"] = " ".join(t.title() for t in name_tokens[:-1])
                    data["middle_name"] = name_tokens[-1].title()
                else:
                    data["first_name"] = name_tokens[0].title()
                    if len(name_tokens) > 1:
                        data["middle_name"] = " ".join(t.title() for t in name_tokens[1:])

            if len(parts) > 3 and re.match(r"^\d{6}$", parts[3]):
                yymmdd = parts[3]
                yy = int(yymmdd[0:2])
                mm = int(yymmdd[2:4])
                dd = int(yymmdd[4:6])
                yyyy = 2000 + yy if yy <= 30 else 1900 + yy
                data["birth_date"] = f"{yyyy:04d}-{mm:02d}-{dd:02d}"

            if len(parts) > 4:
                sex = parts[4].upper()
                if sex in {"M", "MALE"}:
                    data["gender"] = "Male"
                elif sex in {"F", "FEMALE"}:
                    data["gender"] = "Female"

            if len(parts) > 2:
                civil_code = parts[2].strip()
                civil_map = {
                    "1": "Single",
                    "2": "Married",
                    "3": "Widowed",
                    "4": "Separated",
                    "5": "Divorced",
                }
                if civil_code in civil_map:
                    data["civil_status"] = civil_map[civil_code]

    # 4) key:value text payload
    if not data:
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key_n = re.sub(r"[^a-z0-9]", "", key.lower())
            val = val.strip()
            key_map = {
                "firstname": "first_name",
                "middlename": "middle_name",
                "lastname": "last_name",
                "suffix": "suffix",
                "birthdate": "birth_date",
                "dateofbirth": "birth_date",
                "gender": "gender",
                "sex": "gender",
                "civilstatus": "civil_status",
                "birthplace": "place_of_birth",
                "placeofbirth": "place_of_birth",
                "precinct": "precinct",
                "precint": "precinct",
                "nationality": "nationality",
                "religion": "religion",
            }
            if key_n in key_map and val:
                data[key_map[key_n]] = val

    # Normalize common values
    if "gender" in data:
        g = data["gender"].strip().upper()
        if g in {"M", "MALE"}:
            data["gender"] = "Male"
        elif g in {"F", "FEMALE"}:
            data["gender"] = "Female"

    if "birth_date" in data:
        normalized = _extract_resident_data_from_ocr(f"birthdate: {data['birth_date']}").get("birth_date")
        if normalized:
            data["birth_date"] = normalized

    return _normalize_extracted_name_fields(data, raw)


def _extract_qcid_data_from_ocr(text):
    cleaned = text or ""
    upper_text = cleaned.upper()
    if "QCID" not in upper_text and "QUEZON CITY" not in upper_text and "QC ID" not in upper_text:
        return {}

    lines = [ln.strip() for ln in re.sub(r"\r", "", cleaned).split("\n") if ln.strip()]

    def normalize(s):
        s = s.upper()
        s = s.replace("0", "O").replace("1", "I").replace("5", "S")
        return re.sub(r"[^A-Z0-9]", "", s)

    norm_lines = [normalize(ln) for ln in lines]

    aliases = {
        "first_name": ["FIRSTNAME", "GIVENNAME"],
        "middle_name": ["MIDDLENAME", "MIDNAME", "MIDDLEINITIAL"],
        "last_name": ["LASTNAME", "SURNAME", "FAMILYNAME"],
        "birth_date": ["BIRTHDATE", "DATEOFBIRTH", "DOB"],
        "place_of_birth": ["BIRTHPLACE", "PLACEOFBIRTH", "POB"],
        "gender": ["SEX", "GENDER"],
        "civil_status": ["CIVILSTATUS"],
        "precinct": ["PRECINCT", "PRECINT"],
    }
    all_labels = [a for group in aliases.values() for a in group]

    def has_any_label(norm_line):
        return any(lbl in norm_line for lbl in all_labels)

    def normalize_date(raw):
        if not raw:
            return None
        raw = raw.strip()
        m = re.search(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", raw)
        if m:
            parts = re.split(r"[\/\-]", m.group(1))
            mm, dd, yy = parts
            yyyy = int(yy)
            if yyyy < 100:
                yyyy += 2000 if yyyy < 50 else 1900
            return f"{yyyy:04d}-{int(mm):02d}-{int(dd):02d}"
        m = re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2})\s+(\d{4})", raw.upper())
        if m:
            months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
            mon, dd, yyyy = m.groups()
            return f"{int(yyyy):04d}-{months[mon[:3]]:02d}-{int(dd):02d}"
        return None

    def extract_value_for(field_key):
        label_variants = aliases[field_key]
        for idx, norm_line in enumerate(norm_lines):
            matched_label = next((lbl for lbl in label_variants if lbl in norm_line), None)
            if not matched_label:
                continue

            original_line = lines[idx]
            inline = re.split(r"[:\-]", original_line, maxsplit=1)
            if len(inline) == 2 and inline[1].strip():
                return inline[1].strip()

            if idx + 1 < len(lines):
                nxt_norm = norm_lines[idx + 1]
                if not has_any_label(nxt_norm):
                    return lines[idx + 1].strip()
        return None

    data = {}

    # Strong-name line pattern on QCID:
    # "SARMIENTO, JOHN RICHMOND PAGADUAN"
    for ln in lines:
        if "," not in ln:
            continue
        if re.search(r"\d", ln):
            continue
        if len(ln) < 8:
            continue
        upper_ln = ln.upper()
        if any(x in upper_ln for x in ["STREET", "QUEZON", "CITY", "BARANGAY", "BLOOD TYPE", "DATE ISSUED", "VALID UNTIL"]):
            continue
        left, right = ln.split(",", 1)
        left_clean = re.sub(r"[^A-Za-z\-\s]", "", left).strip()
        right_tokens = [re.sub(r"[^A-Za-z\-\s]", "", t).strip() for t in right.strip().split()]
        right_tokens = [t for t in right_tokens if t]
        if left_clean and right_tokens:
            # For QCID, treat last token as middle name (often middle surname),
            # everything before that is first name.
            if len(right_tokens) >= 2:
                data["first_name"] = " ".join(t.title() for t in right_tokens[:-1]).strip()
                data["middle_name"] = right_tokens[-1].title()
            else:
                data["first_name"] = right_tokens[0].title()
            data["last_name"] = left_clean.title()
            break
    for field in aliases:
        if data.get(field):
            continue
        val = extract_value_for(field)
        if not val:
            continue
        if field == "gender":
            v = val.upper()
            if re.search(r"\bMALE\b", v) or re.search(r"\bM\b", v):
                data[field] = "Male"
            elif re.search(r"\bFEMALE\b", v) or re.search(r"\bF\b", v):
                data[field] = "Female"
        elif field == "civil_status":
            v = val.upper()
            if "SINGLE" in v:
                data[field] = "Single"
            elif "MARRIED" in v:
                data[field] = "Married"
            elif "WIDOW" in v:
                data[field] = "Widowed"
            elif "SEPARAT" in v:
                data[field] = "Separated"
            elif "DIVORC" in v:
                data[field] = "Divorced"
            else:
                data[field] = val.title()
        elif field == "birth_date":
            dt = normalize_date(val)
            if dt:
                data[field] = dt
        else:
            data[field] = val.title() if field.endswith("name") else val

    if not data.get("first_name") and not data.get("last_name"):
        for ln in lines:
            if "," in ln and len(ln) > 6:
                left, right = ln.split(",", 1)
                left = left.strip()
                right_parts = [p for p in right.strip().split() if p]
                if left and right_parts:
                    data["last_name"] = left.title()
                    data["first_name"] = right_parts[0].title()
                    if len(right_parts) > 1:
                        data["middle_name"] = " ".join(p.title() for p in right_parts[1:])
                    break

    data = _remove_address_like_name_noise(data)
    return data


def _normalize_extracted_name_fields(data, source_text=""):
    first_name = (data.get("first_name") or "").strip()
    middle_name = (data.get("middle_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    def clean_token(token):
        token = re.sub(r"\s+", " ", token).strip(" ,.-")
        return token

    first_name = clean_token(first_name)
    middle_name = clean_token(middle_name)
    last_name = clean_token(last_name)

    # Case: OCR copied the same full name into multiple fields.
    same_nonempty = (
        first_name and middle_name and last_name and
        first_name.upper() == middle_name.upper() == last_name.upper()
    )
    if same_nonempty:
        full = first_name
        if "," in full:
            ln, rest = [p.strip() for p in full.split(",", 1)]
            parts = [p for p in rest.split() if p]
            data["last_name"] = ln.title() if ln else ""
            data["first_name"] = parts[0].title() if parts else ""
            data["middle_name"] = " ".join(p.title() for p in parts[1:]) if len(parts) > 1 else ""
            return data
        parts = [p for p in full.split() if p]
        if len(parts) >= 2:
            data["first_name"] = parts[0].title()
            data["last_name"] = parts[-1].title()
            data["middle_name"] = " ".join(p.title() for p in parts[1:-1]) if len(parts) > 2 else ""
            return data

    # Case: first_name contains full name while middle/last are missing or partial.
    if first_name:
        parts = [p for p in first_name.split() if p]
        if len(parts) >= 2:
            # If last_name is missing or appears only as part of full string, derive from parts.
            if not last_name or (last_name and last_name.upper() in first_name.upper() and len(last_name) <= 3):
                data["last_name"] = parts[-1].title()
            # If middle name appears to be full name, recompute.
            if not middle_name or middle_name.upper() == first_name.upper():
                data["middle_name"] = " ".join(p.title() for p in parts[1:-1]) if len(parts) > 2 else ""
            # Keep first token as first name when it looks like full-name stuffing.
            if first_name.upper() == " ".join(parts).upper():
                data["first_name"] = parts[0].title()

    # Case: first name got split into first+middle fragments (e.g., "JER" + "MIE").
    first_name = (data.get("first_name") or "").strip()
    middle_name = (data.get("middle_name") or "").strip()
    if first_name and middle_name:
        if len(first_name) <= 4 and len(middle_name) <= 6:
            merged = f"{first_name}{middle_name}"
            if re.match(r"^[A-Za-z]+$", merged):
                data["first_name"] = merged.title()
                data["middle_name"] = ""

    # QCID/common OCR case: compound first name split across first/middle
    # when no explicit middle-name label is detected in OCR text.
    first_name = (data.get("first_name") or "").strip()
    middle_name = (data.get("middle_name") or "").strip()
    if source_text and first_name and middle_name:
        upper_source = source_text.upper()
        has_middle_label = (
            "MIDDLE NAME" in upper_source
            or "MIDDLENAME" in re.sub(r"[^A-Z]", "", upper_source)
            or "MIDDLE INITIAL" in upper_source
        )
        if not has_middle_label:
            if (
                len(first_name) <= 6
                and len(middle_name) >= 4
                and re.match(r"^[A-Za-z\- ]+$", first_name)
                and re.match(r"^[A-Za-z\- ]+$", middle_name)
            ):
                data["first_name"] = f"{first_name} {middle_name}".title()
                data["middle_name"] = ""

    # Case: last_name accidentally truncated but present in first_name full string.
    last_name = (data.get("last_name") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    if first_name and last_name and len(last_name) <= 3:
        fparts = [p for p in first_name.split() if p]
        if len(fparts) >= 2:
            data["last_name"] = fparts[-1].title()
            data["first_name"] = fparts[0].title()
            data["middle_name"] = " ".join(p.title() for p in fparts[1:-1]) if len(fparts) > 2 else data.get("middle_name", "")

    # Expand truncated surname using OCR text tokens (e.g., "iento" -> "sarmiento").
    last_name = (data.get("last_name") or "").strip()
    if source_text and last_name and len(last_name) >= 4:
        upper_fragment = re.sub(r"[^A-Z]", "", last_name.upper())
        tokens = re.findall(r"[A-Z]{4,}", source_text.upper())
        candidates = [
            t for t in tokens
            if t.endswith(upper_fragment) and len(t) > len(upper_fragment)
        ]
        if candidates:
            best = max(candidates, key=len)
            data["last_name"] = best.title()

    # If OCR has an obvious "LAST, FIRST MIDDLE" line, prefer it.
    if source_text:
        lines = [ln.strip() for ln in re.sub(r"\r", "", source_text).split("\n") if ln.strip()]
        comma_lines = [ln for ln in lines if "," in ln and not re.search(r"\d", ln)]
        if comma_lines:
            raw = max(comma_lines, key=len)
            left, right = raw.split(",", 1)
            ln = re.sub(r"[^A-Za-z\- ]", "", left).strip()
            rp = [re.sub(r"[^A-Za-z\-]", "", p).strip() for p in right.split()]
            rp = [p for p in rp if p]
            if ln and rp:
                data["last_name"] = ln.title()
                upper_source = source_text.upper()
                is_qcid_context = "QCID" in upper_source or "QUEZON CITY" in upper_source or "QC ID" in upper_source
                if is_qcid_context and len(rp) >= 2:
                    data["first_name"] = " ".join(p.title() for p in rp[:-1]).strip()
                    data["middle_name"] = rp[-1].title()
                else:
                    data["first_name"] = rp[0].title()
                    data["middle_name"] = " ".join(p.title() for p in rp[1:]) if len(rp) > 1 else ""

    # Final QCID-oriented cleanup:
    # remove symbol noise in names and try rebuilding from "LAST, FIRST MIDDLE" segment.
    def clean_name_value(v):
        v = re.sub(r"[^A-Za-z\-\s']", " ", v or "")
        v = re.sub(r"\s+", " ", v).strip()
        return v

    data["first_name"] = clean_name_value(data.get("first_name", ""))
    data["middle_name"] = clean_name_value(data.get("middle_name", ""))
    data["last_name"] = clean_name_value(data.get("last_name", ""))

    if data.get("middle_name", "").upper() in {"", "AND"}:
        data["middle_name"] = ""

    if source_text and data.get("last_name"):
        ln_upper = re.escape(data["last_name"].upper())
        m = re.search(ln_upper + r"\s*,\s*([A-Z .&'-]+)", source_text.upper())
        if m:
            right = m.group(1)
            right_clean = re.sub(r"[^A-Z\s'-]", " ", right)
            tokens = [t for t in right_clean.split() if t]
            if len(tokens) >= 2:
                # Prefer compound first name + trailing middle token for QCID formats.
                rebuilt_first = " ".join(t.title() for t in tokens[:-1]).strip()
                rebuilt_middle = tokens[-1].title()
                if rebuilt_first:
                    data["first_name"] = rebuilt_first
                if rebuilt_middle and len(rebuilt_middle) <= 12:
                    data["middle_name"] = rebuilt_middle

    # If first name looks like clipped token (e.g., Johnp), keep only alphabetic chunk.
    if data.get("first_name"):
        fn = data["first_name"]
        if re.match(r"^[A-Za-z]{5,}$", fn) and fn[-1].islower() is False:
            pass
        # Remove trailing single-char artifact when middle is empty and token looks suspicious.
        if " " not in fn and len(fn) >= 5 and not data.get("middle_name"):
            data["first_name"] = re.sub(r"[^A-Za-z]", "", fn).title()

    return data


def _remove_address_like_name_noise(data):
    def is_address_like(value):
        if not value:
            return False
        up = value.upper()
        if re.search(r"\d", up):
            return True
        address_keywords = [
            "STREET", "ST", "ROAD", "RD", "AVE", "AVENUE", "CITY",
            "QUEZON", "BARANGAY", "PASONG", "TAMO", "MACAYA",
        ]
        return any(k in up for k in address_keywords)

    for key in ["first_name", "middle_name", "last_name"]:
        val = (data.get(key) or "").strip()
        if is_address_like(val):
            data[key] = ""

    return data


def _build_ocr_variants(image):
    from PIL import ImageOps, ImageFilter, ImageEnhance

    variants = []
    base = image.convert("RGB")
    variants.append(("original", base))

    gray = ImageOps.grayscale(base)
    variants.append(("gray", gray))

    auto = ImageOps.autocontrast(gray)
    variants.append(("autocontrast", auto))

    sharp = auto.filter(ImageFilter.SHARPEN)
    variants.append(("sharpen", sharp))

    high_contrast = ImageEnhance.Contrast(auto).enhance(2.0)
    variants.append(("high_contrast", high_contrast))

    bw = high_contrast.point(lambda px: 255 if px > 150 else 0)
    variants.append(("threshold_bw", bw))

    w, h = base.size
    upscale = base.resize((max(1, int(w * 1.8)), max(1, int(h * 1.8))))
    variants.append(("upscale", upscale))

    return variants


def _best_ocr_extraction(image, pytesseract):
    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 4",
        "--oem 3 --psm 11",
    ]

    best = {
        "score": -1,
        "text": "",
        "data": {},
    }
    results = []

    variants = _build_ocr_variants(image)
    for _, img_variant in variants:
        for cfg in configs:
            try:
                text = pytesseract.image_to_string(img_variant, lang="eng", config=cfg)
            except Exception:
                continue
            data = _extract_resident_data_from_ocr(text)
            score = len(data.keys())

            if data.get("first_name"):
                score += 1
            if data.get("last_name"):
                score += 1
            if data.get("birth_date"):
                score += 1
            if data.get("gender"):
                score += 2
            if data.get("civil_status"):
                score += 2
            if data.get("precinct"):
                score += 2

            # Penalize results that only contain name-like fields.
            if data and set(data.keys()).issubset({"first_name", "middle_name", "last_name", "suffix"}):
                score -= 2

            results.append({
                "score": score,
                "text": text,
                "data": data,
            })

            if score > best["score"]:
                best = {
                    "score": score,
                    "text": text,
                    "data": data,
                }

    # Merge fields from top OCR passes so we don't lose non-name fields
    # when one pass is strong on names but weak on demographics.
    merged = {}
    for res in sorted(results, key=lambda r: r["score"], reverse=True)[:10]:
        for key, value in (res["data"] or {}).items():
            if not value:
                continue
            if key not in merged:
                merged[key] = value
                continue

            # Prefer longer values for likely truncated names/places.
            if key in {"first_name", "middle_name", "last_name", "place_of_birth"}:
                if len(str(value)) > len(str(merged[key])):
                    merged[key] = value

    merged = _normalize_extracted_name_fields(merged, best["text"])
    return {
        "score": best["score"],
        "text": best["text"],
        "data": merged,
    }


def _find_tesseract_binary():
    tesseract_bin = shutil.which("tesseract")
    if tesseract_bin:
        return tesseract_bin

    env_candidate = os.environ.get("TESSERACT_CMD")
    if env_candidate and Path(env_candidate).exists():
        return env_candidate

    common_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe"),
        str(Path.home() / "scoop/apps/tesseract/current/tesseract.exe"),
    ]
    for candidate in common_paths:
        if Path(candidate).exists():
            return candidate
    return None


@group_required(is_staff_user)
def scan_resident_id(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Invalid request method."}, status=405)

    id_image = request.FILES.get("id_image")
    if not id_image:
        return JsonResponse({"ok": False, "error": "No ID image uploaded."}, status=400)

    try:
        from PIL import Image
    except ImportError:
        return JsonResponse({
            "ok": False,
            "error": "Image scanning dependencies are not installed. Install 'Pillow' first.",
        }, status=500)

    pytesseract = None
    tesseract_bin = None
    try:
        import pytesseract as pytesseract_module
        pytesseract = pytesseract_module
        tesseract_bin = _find_tesseract_binary()
        if tesseract_bin:
            pytesseract.pytesseract.tesseract_cmd = tesseract_bin
    except ImportError:
        pytesseract = None

    try:
        image = Image.open(id_image)
        qr_result = _try_decode_qr_payloads(image)
        qr_payloads = qr_result.get("payloads", [])
        qr_detected = qr_result.get("qr_detected", False)
        qr_data = {}
        for payload in qr_payloads:
            parsed = _extract_resident_data_from_qr_payload(payload)
            for k, v in parsed.items():
                if v and k not in qr_data:
                    qr_data[k] = v

        # If a QR is clearly detected but cannot be decoded, don't OCR fallback
        # because OCR on QR modules produces garbage names.
        if qr_detected and not qr_data:
            return JsonResponse({
                "ok": False,
                "error": (
                    "QR code detected but could not be decoded. "
                    "Try recropping tighter around the QR, keep it straight, and use a clearer image."
                ),
            }, status=422)

        best = {"score": -1, "text": "", "data": {}}
        ocr_text = ""
        if pytesseract and tesseract_bin:
            best = _best_ocr_extraction(image, pytesseract)
            ocr_text = best["text"]
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read image: {exc}"}, status=500)

    extracted = best["data"] if best else {}
    # Prefer QR values when available, then fill gaps from OCR.
    if qr_data:
        merged = dict(qr_data)
        for k, v in (extracted or {}).items():
            if k not in merged and v:
                merged[k] = v
        extracted = merged

    if not extracted:
        if not tesseract_bin:
            return JsonResponse({
                "ok": False,
                "error": (
                    "This ID could not be auto-filled because no readable QR data was found and the full OCR engine "
                    "is not installed yet. Install Tesseract to scan text-based IDs smoothly."
                ),
                "needs_tesseract": True,
            }, status=422)
        preview = re.sub(r"\s+", " ", (ocr_text or "")).strip()[:280]
        return JsonResponse({
            "ok": False,
            "error": "No recognizable resident fields found from the scanned ID.",
            "ocr_preview": preview,
        }, status=422)

    response_payload = {"ok": True, "data": extracted}
    if not tesseract_bin:
        response_payload["warning"] = (
            "QR-based fields were applied. Install Tesseract as well if you want text-only IDs to auto-fill smoothly."
        )
    return JsonResponse(response_payload)

# CAPTAIN DASHBOARD
# CAPTAIN DASHBOARD
# CAPTAIN DASHBOARD

@login_required
@user_passes_test(is_captain)
def dashboard(request):
    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    residents = Resident.objects.select_related("household__purok").all()
    service_requests = ServiceRequest.objects.select_related("resident", "service_type").all()
    complaints = Complaint.objects.select_related("resident").all()

    total_residents = residents.count()
    total_households = Household.objects.count()
    male_residents = residents.filter(gender="Male").count()
    female_residents = residents.filter(gender="Female").count()

    alive = residents.filter(status="Alive").count()
    deceased = residents.filter(status="Deceased").count()
    moved = residents.filter(status="Moved").count()

    children = youth = adults = seniors = 0
    for resident in residents:
        age = resident.age
        if age is None:
            continue
        if age <= 12:
            children += 1
        elif age <= 17:
            youth += 1
        elif age <= 59:
            adults += 1
        else:
            seniors += 1

    documents_issued = service_requests.count()
    approved_requests = service_requests.filter(status="Ready for Release").count()
    released_requests = service_requests.filter(status="Released").count()
    pending_requests = service_requests.filter(status="Submitted").count()
    review_requests = service_requests.filter(status="Under Review").count()
    validation_requests = service_requests.filter(status="For Validation").count()
    processing_requests = service_requests.filter(status="Processing").count()
    rejected_requests = service_requests.filter(status="Rejected").count()

    total_complaints = complaints.count()
    review_complaints = complaints.filter(status__in=["Submitted", "Under Review"]).count()
    scheduled_complaints = complaints.filter(status__in=["For Scheduling", "Scheduled for Hearing", "Ongoing Mediation"]).count()
    resolved_complaints = complaints.filter(status="Resolved / Settled").count()
    unresolved_complaints = complaints.filter(status="Unresolved").count()
    withdrawn_complaints = complaints.filter(status="Withdrawn").count()
    open_complaints = complaints.filter(status__in=COMPLAINT_OPEN_STATUSES).count()

    total_revenue = Payment.objects.aggregate(total=Sum("amount"))["total"] or 0
    month_revenue = Payment.objects.filter(payment_date__date__gte=current_month_start).aggregate(total=Sum("amount"))["total"] or 0

    recent_requests = service_requests.order_by("-request_date")[:5]
    recent_complaints = complaints.order_by("-date_filed")[:5]
    recent_residents = residents.order_by("-created_at")[:5]

    pending_verifications = UserProfile.objects.filter(is_verified=False, user__is_active=True).select_related("user", "resident")
    pending_verification_count = pending_verifications.count()

    overdue_requests = service_requests.filter(
        status__in=["Submitted", "Under Review", "For Validation", "Processing", "Pending Requirements", "On Hold"],
        request_date__date__lt=today - timedelta(days=5),
    ).count()

    for_approval_count = service_requests.filter(status="Ready for Release").count() + complaints.filter(status__in=["For Scheduling", "Scheduled for Hearing"]).count()

    monthly_resident_additions = residents.filter(created_at__date__gte=current_month_start).count()
    previous_month_resident_additions = residents.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    ).count()
    monthly_complaints = complaints.filter(date_filed__date__gte=current_month_start).count()
    previous_month_complaints = complaints.filter(
        date_filed__date__gte=previous_month_start,
        date_filed__date__lte=previous_month_end,
    ).count()
    monthly_service_requests = service_requests.filter(request_date__date__gte=current_month_start).count()
    previous_month_service_requests = service_requests.filter(
        request_date__date__gte=previous_month_start,
        request_date__date__lte=previous_month_end,
    ).count()

    trend_cards = [
        {
            "label": "Residents Added This Month",
            "value": monthly_resident_additions,
            "change": monthly_resident_additions - previous_month_resident_additions,
            "tone": "blue",
        },
        {
            "label": "Complaints This Month",
            "value": monthly_complaints,
            "change": monthly_complaints - previous_month_complaints,
            "tone": "amber",
        },
        {
            "label": "Service Requests This Month",
            "value": monthly_service_requests,
            "change": monthly_service_requests - previous_month_service_requests,
            "tone": "teal",
        },
    ]

    purok_stats = list(
        residents.filter(household__purok__isnull=False).values(
            "household__purok__name"
        ).annotate(
            resident_count=Count("id")
        ).order_by("-resident_count", "household__purok__name")
    )
    max_purok_count = max((item["resident_count"] for item in purok_stats), default=1)
    for item in purok_stats:
        item["pct"] = round((item["resident_count"] / max_purok_count) * 100)

    complaint_hotspots = list(
        complaints.filter(resident__household__purok__isnull=False).values(
            "resident__household__purok__name"
        ).annotate(total=Count("id")).order_by("-total", "resident__household__purok__name")
    )

    popular_service = service_requests.values("service_type__name").annotate(total=Count("id")).order_by("-total", "service_type__name").first()
    common_complaint = complaints.values("title").annotate(total=Count("id")).order_by("-total", "title").first()
    top_purok_residents = purok_stats[0] if purok_stats else None
    top_purok_complaints = complaint_hotspots[0] if complaint_hotspots else None

    priority_actions = [
        {
            "label": "Pending Resident Verifications",
            "count": pending_verification_count,
            "description": "Resident portal accounts waiting for captain oversight.",
            "url": "pending_verifications",
        },
        {
            "label": "Complaints Requiring Attention",
            "count": open_complaints,
            "description": "Open barangay complaints still unresolved or under review.",
            "url": "complaint_list",
        },
        {
            "label": "Approvals and Sign-offs",
            "count": for_approval_count,
            "description": "Requests already prepared for release and complaints ready for decision.",
            "url": "service_requests",
        },
        {
            "label": "Overdue Service Requests",
            "count": overdue_requests,
            "description": "Requests staying too long in the queue and needing follow-up.",
            "url": "service_requests",
        },
    ]

    activity_items = []
    for resident in recent_residents[:2]:
        activity_items.append({
            "name": f"{resident.first_name} {resident.last_name}",
            "description": "was added to resident records.",
            "timestamp": resident.created_at,
            "type": "resident",
        })
    for complaint in recent_complaints[:2]:
        activity_items.append({
            "name": f"{complaint.resident.first_name} {complaint.resident.last_name}",
            "description": f"filed complaint: {complaint.title}.",
            "timestamp": complaint.date_filed,
            "type": "complaint",
        })
    for service_request in recent_requests[:2]:
        activity_items.append({
            "name": f"{service_request.resident.first_name} {service_request.resident.last_name}",
            "description": f"requested {service_request.service_type.name}.",
            "timestamp": service_request.request_date,
            "type": "service",
        })
    activity_items = sorted(activity_items, key=lambda item: item["timestamp"], reverse=True)[:6]

    health_cards = [
        {"label": "Open Complaints", "value": open_complaints, "sub": "Active issues across the barangay", "tone": "red"},
        {"label": "Resolved This Month", "value": complaints.filter(status="Resolved / Settled", updated_at__date__gte=current_month_start).count(), "sub": "Complaints settled this month", "tone": "green"},
        {"label": "Pending Requests", "value": pending_requests + review_requests + validation_requests + processing_requests, "sub": "Service queue currently in progress", "tone": "blue"},
        {"label": "Released This Week", "value": service_requests.filter(status="Released", processed_date__date__gte=today - timedelta(days=7)).count(), "sub": "Documents released in the last 7 days", "tone": "purple"},
        {"label": "Revenue This Month", "value": f"₱{month_revenue}", "sub": "Collections recorded this month", "tone": "teal"},
    ]

    quick_actions = [
        {"label": "Review Complaints", "url": "complaint_list", "tone": "red"},
        {"label": "View Audit Logs", "url": "audit_logs", "tone": "amber"},
        {"label": "Export Monthly Summary", "url": "export_summary", "tone": "blue"},
        {"label": "View Households", "url": "household_list", "tone": "sky"},
        {"label": "Review Service Requests", "url": "service_requests", "tone": "green"},
    ]

    notices = [
        {"title": "Pending verification queue", "text": f"{pending_verification_count} resident account(s) are waiting for verification."},
        {"title": "Open complaint watch", "text": f"{open_complaints} complaint(s) still require barangay action."},
        {"title": "Monthly service demand", "text": f"{monthly_service_requests} service request(s) were submitted this month."},
    ]
    if overdue_requests:
        notices.insert(0, {"title": "Overdue service requests", "text": f"{overdue_requests} request(s) are older than five days and should be escalated."})

    context = {
        "total_residents": total_residents,
        "total_households": total_households,
        "male_residents": male_residents,
        "female_residents": female_residents,
        "children": children,
        "youth": youth,
        "adults": adults,
        "seniors": seniors,
        "alive": alive,
        "deceased": deceased,
        "moved": moved,
        "documents_issued": documents_issued,
        "approved_requests": approved_requests,
        "released_requests": released_requests,
        "pending_requests": pending_requests,
        "processing_requests": processing_requests,
        "rejected_requests": rejected_requests,
        "total_revenue": total_revenue,
        "month_revenue": month_revenue,
        "purok_stats": purok_stats,
        "recent_requests": recent_requests,
        "recent_complaints": recent_complaints,
        "recent_residents": recent_residents,
        "total_complaints": total_complaints,
        "review_complaints": review_complaints,
        "scheduled_complaints": scheduled_complaints,
        "resolved_complaints": resolved_complaints,
        "unresolved_complaints": unresolved_complaints,
        "withdrawn_complaints": withdrawn_complaints,
        "open_complaints": open_complaints,
        "pending_verification_count": pending_verification_count,
        "priority_actions": priority_actions,
        "activity_items": activity_items,
        "health_cards": health_cards,
        "trend_cards": trend_cards,
        "popular_service": popular_service,
        "common_complaint": common_complaint,
        "top_purok_residents": top_purok_residents,
        "top_purok_complaints": top_purok_complaints,
        "quick_actions": quick_actions,
        "notices": notices,
        "today": today,
    }

    return render(request, "dashboard.html", context)

#ROLE-BASED REDIRECT
#ROLE-BASED REDIRECT
#ROLE-BASED REDIRECT
@login_required
def role_redirect(request):
    if request.user.groups.filter(name='Captain').exists():
        return redirect('captain_dashboard')

    elif request.user.groups.filter(name='Secretary').exists():
        return redirect('secretary_dashboard')

    elif request.user.groups.filter(name='Treasurer').exists():
        return redirect('treasurer_dashboard')

    elif request.user.groups.filter(name='Staff').exists():
        return redirect('staff_dashboard')

    elif is_resident(request.user):
        profile = get_user_profile(request.user)
        if profile and profile.is_verified and profile.resident:
            return redirect("portal_create_service_request")
        return redirect("portal_pending_verification")

    else:
        profile = get_user_profile(request.user)
        if profile:
            if profile.is_verified and profile.resident:
                return redirect("portal_create_service_request")
            return redirect("portal_pending_verification")
        return redirect('admin/')


def resident_register(request):
    if request.user.is_authenticated:
        return redirect("role_redirect")

    if request.method == "POST":
        form = ResidentPortalRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.first_name = form.cleaned_data["first_name"].strip()
                user.last_name = form.cleaned_data["last_name"].strip()
                user.email = form.cleaned_data.get("email", "").strip()
                user.save()

                resident_group, _ = Group.objects.get_or_create(name="Resident")
                user.groups.clear()
                user.groups.add(resident_group)

                first_name = form.cleaned_data["first_name"].strip()
                middle_name = form.cleaned_data.get("middle_name", "").strip()
                last_name = form.cleaned_data["last_name"].strip()
                suffix = form.cleaned_data.get("suffix", "").strip()
                birth_date = form.cleaned_data["birthdate"]
                place_of_birth = form.cleaned_data.get("place_of_birth", "").strip()
                gender = form.cleaned_data.get("gender", "")
                civil_status = form.cleaned_data.get("civil_status", "")
                nationality = form.cleaned_data.get("nationality", "").strip()
                religion = form.cleaned_data.get("religion", "").strip()
                occupation = form.cleaned_data.get("occupation", "").strip()
                educational_attainment = form.cleaned_data.get("educational_attainment", "")
                contact_number = form.cleaned_data.get("contact_number", "").strip()
                precinct = form.cleaned_data.get("precinct", "").strip()
                pwd = form.cleaned_data.get("pwd", False)
                indigenous = form.cleaned_data.get("indigenous", False)
                solo_parent = form.cleaned_data.get("solo_parent", False)
                voter_status = form.cleaned_data.get("voter_status", False)
                status = form.cleaned_data.get("status", "Alive")
                address = form.cleaned_data["address"].strip()
                valid_id_image = form.cleaned_data["valid_id_image"]

                linked_resident = Resident.objects.filter(
                    first_name__iexact=first_name,
                    last_name__iexact=last_name,
                    birth_date=birth_date,
                    user_profile__isnull=True,
                ).first()

                profile = UserProfile.objects.create(
                    user=user,
                    resident=linked_resident,
                    first_name=first_name,
                    middle_name=middle_name,
                    last_name=last_name,
                    suffix=suffix,
                    birth_date=birth_date,
                    place_of_birth=place_of_birth,
                    gender=gender,
                    civil_status=civil_status,
                    nationality=nationality,
                    religion=religion,
                    occupation=occupation,
                    educational_attainment=educational_attainment,
                    pwd=pwd,
                    indigenous=indigenous,
                    solo_parent=solo_parent,
                    voter_status=voter_status,
                    status=status,
                    contact_number=contact_number,
                    precinct=precinct,
                    address=address,
                    valid_id_image=valid_id_image,
                    is_verified=False,
                    is_auto_matched=bool(linked_resident),
                )

                transaction.on_commit(
                    lambda profile_id=profile.id: notify_secretaries_of_pending_registration(
                        request,
                        UserProfile.objects.select_related("user").get(pk=profile_id),
                    )
                )

            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

            if linked_resident:
                messages.info(
                    request,
                    "Registration successful. A matching resident record was found but still requires secretary verification.",
                )
            else:
                messages.info(request, "Registration successful. Your account is pending secretary verification.")
            return redirect("portal_pending_verification")
    else:
        form = ResidentPortalRegistrationForm()

    return render(request, "resident_register.html", {"form": form})


@login_required
def portal_pending_verification(request):
    if is_staff_user(request.user):
        return redirect("role_redirect")

    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, "Resident profile not found. Please register first.")
        return redirect("resident_register")

    if profile.is_verified and profile.resident:
        return redirect("portal_create_service_request")

    return render(request, "portal_pending_verification.html", {"profile": profile})


@login_required
def pending_verifications(request):
    if not (is_secretary(request.user) or is_captain(request.user)):
        return HttpResponseForbidden("You do not have permission to access this page.")
    profiles = UserProfile.objects.filter(
        is_verified=False,
        user__is_active=True,
    ).select_related("user", "resident")

    return render(request, "pending_verifications.html", {
        "profiles": profiles,
        "can_manage": is_secretary(request.user),
    })


@login_required
def review_pending_verification(request, profile_id):
    if not (is_secretary(request.user) or is_captain(request.user)):
        return HttpResponseForbidden("You do not have permission to access this page.")
    profile = get_object_or_404(
        UserProfile.objects.select_related("user", "resident"),
        id=profile_id,
        is_verified=False,
        user__is_active=True,
    )

    suggested_residents = Resident.objects.filter(
        first_name__iexact=profile.first_name,
        last_name__iexact=profile.last_name,
        birth_date=profile.birth_date,
    ).select_related("household")

    available_residents = Resident.objects.filter(
        user_profile__isnull=True
    ).exclude(
        id__in=suggested_residents.values("id")
    ).order_by("last_name", "first_name")

    create_form = ResidentVerificationCreateForm(initial={
        "first_name": profile.first_name,
        "middle_name": profile.middle_name,
        "last_name": profile.last_name,
        "suffix": profile.suffix,
        "birth_date": profile.birth_date,
        "place_of_birth": profile.place_of_birth,
        "gender": profile.gender,
        "civil_status": profile.civil_status,
        "nationality": profile.nationality,
        "religion": profile.religion,
        "occupation": profile.occupation,
        "educational_attainment": profile.educational_attainment,
        "contact_number": profile.contact_number,
        "email": profile.user.email,
        "voter_status": profile.voter_status,
        "status": profile.status or "Alive",
    })
    mismatch_warning = False
    mismatch_details = []
    selected_resident_id = None

    can_manage = is_secretary(request.user)

    if request.method == "POST":
        if not can_manage:
            return HttpResponseForbidden("Only the Secretary can manage pending verifications.")
        action = request.POST.get("action")

        if action == "approve":
            resident_id = request.POST.get("resident_id")
            resident = get_object_or_404(Resident, id=resident_id)
            selected_resident_id = resident.id
            if hasattr(resident, "user_profile") and resident.user_profile.user_id != profile.user_id:
                messages.error(request, "Selected resident record is already linked to another account.")
                return redirect("review_pending_verification", profile_id=profile.id)

            mismatch_details = []
            if (profile.first_name or "").strip().lower() != (resident.first_name or "").strip().lower():
                mismatch_details.append("First name does not match.")
            if (profile.last_name or "").strip().lower() != (resident.last_name or "").strip().lower():
                mismatch_details.append("Last name does not match.")
            if profile.birth_date != resident.birth_date:
                mismatch_details.append("Birthdate does not match.")

            mismatch_warning = len(mismatch_details) > 0
            confirm_override = request.POST.get("confirm_override") in ("1", "true", "True", "on", "yes")

            if mismatch_warning and not confirm_override:
                messages.warning(request, "Warning: The entered data does not match the selected resident.")
            else:
                before_data = snapshot_instance(profile)
                profile.resident = resident
                profile.is_verified = True
                profile.is_auto_matched = not mismatch_warning
                profile.save(update_fields=["resident", "is_verified", "is_auto_matched", "updated_at"])

                verification_mode = (
                    "Verified resident (manual override with mismatch)"
                    if mismatch_warning
                    else "Verified resident (auto match)"
                )

                log_audit_event(
                    action="UPDATE",
                    model_name="UserProfile",
                    description=(
                        f"{verification_mode}: Linked user {profile.user.username} "
                        f"to resident {resident.id}."
                    ),
                    user=request.user,
                    target_id=profile.id,
                    before_data=before_data,
                    after_data=snapshot_instance(profile),
                    request=request,
                )

                notify_resident_registration_decision(profile, approved=True)
                messages.success(request, f"Verified account for {profile.user.username}.")
                return redirect("pending_verifications")

        if action == "create":
            create_form = ResidentVerificationCreateForm(request.POST)
            if create_form.is_valid():
                resident = create_form.save(commit=False)
                resident.place_of_birth = resident.place_of_birth or profile.place_of_birth
                resident.nationality = resident.nationality or profile.nationality
                resident.religion = resident.religion or profile.religion
                resident.occupation = resident.occupation or profile.occupation
                resident.educational_attainment = resident.educational_attainment or profile.educational_attainment
                resident.pwd = resident.pwd or profile.pwd
                resident.indigenous = resident.indigenous or profile.indigenous
                resident.solo_parent = resident.solo_parent or profile.solo_parent
                resident.precinct = resident.precinct or profile.precinct
                resident.save()
                before_data = snapshot_instance(profile)
                profile.resident = resident
                profile.is_verified = True
                profile.is_auto_matched = False
                profile.save(update_fields=["resident", "is_verified", "is_auto_matched", "updated_at"])
                log_audit_event(
                    action="UPDATE",
                    model_name="UserProfile",
                    description=(
                        f"Verified resident (manual resident creation): Linked user "
                        f"{profile.user.username} to resident {resident.id}."
                    ),
                    user=request.user,
                    target_id=profile.id,
                    before_data=before_data,
                    after_data=snapshot_instance(profile),
                    request=request,
                )
                notify_resident_registration_decision(profile, approved=True)
                messages.success(request, f"Created new resident and verified {profile.user.username}.")
                return redirect("pending_verifications")
        elif action == "reject":
            before_data = snapshot_instance(profile)
            profile.user.is_active = False
            profile.user.save(update_fields=["is_active"])
            profile.resident = None
            profile.is_verified = False
            profile.is_auto_matched = False
            profile.save(update_fields=["resident", "is_verified", "is_auto_matched", "updated_at"])
            log_audit_event(
                action="UPDATE",
                model_name="UserProfile",
                description=f"Rejected resident verification for user {profile.user.username}.",
                user=request.user,
                target_id=profile.id,
                before_data=before_data,
                after_data=snapshot_instance(profile),
                request=request,
            )
            notify_resident_registration_decision(profile, approved=False)
            messages.warning(request, f"Rejected account {profile.user.username}.")
            return redirect("pending_verifications")

    return render(request, "review_pending_verification.html", {
        "profile": profile,
        "suggested_residents": suggested_residents,
        "available_residents": available_residents,
        "create_form": create_form,
        "mismatch_warning": mismatch_warning,
        "mismatch_details": mismatch_details,
        "selected_resident_id": selected_resident_id,
        "can_manage": can_manage,
    })


@login_required
def portal_create_service_request(request):
    profile, response = get_resident_portal_context(request)
    if response:
        return response

    resident = profile.resident
    service_cards = get_portal_services()
    for service_card in service_cards:
        service_card["fee_value"] = service_card["voter_fee"] if resident.voter_status else service_card["non_voter_fee"]

    recent_requests = (
        ServiceRequest.objects.filter(resident=resident)
        .select_related("service_type")
        .order_by("-request_date")[:5]
    )

    return render(request, "portal_service_request_catalog.html", {
        "resident": resident,
        "service_cards": service_cards,
        "recent_requests": recent_requests,
        "service_categories": [
            {"key": "all", "label": "All Services"},
            {"key": "certificates", "label": "Certificates"},
            {"key": "identification", "label": "Identification"},
            {"key": "employment", "label": "Employment"},
            {"key": "others", "label": "Others"},
        ],
    })


@login_required
def portal_service_request_type(request, service_slug):
    profile, response = get_resident_portal_context(request)
    if response:
        return response

    resident = profile.resident
    service_types = ServiceType.objects.order_by("name")
    selected_service = get_portal_service_by_slug(service_slug)
    if not selected_service:
        return redirect("portal_create_service_request")

    service_purposes = RequestPurpose.objects.filter(is_active=True)

    if request.method == "POST":
        service, context = handle_service_request_submission(
            request,
            resident,
            service_types,
            service_purposes,
            selected_service=selected_service,
        )
        if context is not None:
            return render(request, "portal_service_request_form.html", context)
        return redirect("service_request_detail", request_id=service.id)

    return render(
        request,
        "portal_service_request_form.html",
        build_service_request_form_context(
            request,
            resident,
            service_types,
            service_purposes,
            selected_service=selected_service,
        ),
    )


@login_required
def portal_my_profile(request):
    if not is_resident(request.user):
        return HttpResponseForbidden("Only resident accounts can access this page.")

    profile = get_user_profile(request.user)
    if not profile or not profile.resident:
        messages.error(request, "Your resident profile is not linked yet.")
        return redirect("portal_pending_verification")
    if not profile.is_verified:
        messages.error(request, "Your account is still pending verification.")
        return redirect("portal_pending_verification")

    return redirect("resident_profile", resident_id=profile.resident_id)

#SECRETARY DASHBOARD
#SECRETARY DASHBOARD
#SECRETARY DASHBOARD
@group_required(is_secretary)
def secretary_dashboard(request):
    today = timezone.localdate()

    resident_count = Resident.objects.count()
    household_count = Household.objects.count()
    pending_verification_count = UserProfile.objects.filter(
        is_verified=False,
        user__is_active=True,
    ).count()
    open_complaint_count = Complaint.objects.filter(status__in=COMPLAINT_OPEN_STATUSES).count()
    pending_service_request_count = ServiceRequest.objects.filter(
        status__in=["Submitted", "Under Review", "For Validation", "Processing", "Pending Requirements", "On Hold"]
    ).count()
    certifications_issued_today = ServiceRequest.objects.filter(
        status="Released",
        processed_date__date=today,
    ).count()

    kpis = [
        {
            "label": "Total Residents",
            "value": resident_count or 5438,
            "icon": "residents",
            "tone": "blue",
        },
        {
            "label": "Total Households",
            "value": household_count or 1265,
            "icon": "households",
            "tone": "sky",
        },
        {
            "label": "Pending Verifications",
            "value": pending_verification_count or 8,
            "icon": "verification",
            "tone": "amber",
        },
        {
            "label": "Open Complaints",
            "value": open_complaint_count or 5,
            "icon": "complaints",
            "tone": "rose",
        },
        {
            "label": "Pending Service Requests",
            "value": pending_service_request_count or 4,
            "icon": "services",
            "tone": "violet",
        },
        {
            "label": "Certifications Issued Today",
            "value": certifications_issued_today or 7,
            "icon": "certifications",
            "tone": "teal",
        },
    ]

    pending_actions = [
        {
            "label": "Pending Resident Verifications",
            "count": pending_verification_count or 8,
            "url": "pending_verifications",
        },
        {
            "label": "Complaints to Address",
            "count": open_complaint_count or 5,
            "url": "complaint_list",
        },
        {
            "label": "Service Requests Pending",
            "count": pending_service_request_count or 4,
            "url": "service_requests",
        },
        {
            "label": "Ready for Release",
            "count": ServiceRequest.objects.filter(status="Ready for Release").count() or 7,
            "url": "service_requests",
        },
    ]

    activity_items = []

    for resident in Resident.objects.order_by("-created_at")[:3]:
        activity_items.append({
            "name": f"{resident.first_name} {resident.last_name}",
            "description": "was added as a new resident.",
            "timestamp": resident.created_at,
            "avatar": f"{resident.first_name[:1]}{resident.last_name[:1]}".upper(),
        })

    for complaint in Complaint.objects.select_related("resident").order_by("-date_filed")[:2]:
        activity_items.append({
            "name": f"{complaint.resident.first_name} {complaint.resident.last_name}",
            "description": f"submitted a complaint about {complaint.title.lower()}.",
            "timestamp": complaint.date_filed,
            "avatar": f"{complaint.resident.first_name[:1]}{complaint.resident.last_name[:1]}".upper(),
        })

    for service_request in ServiceRequest.objects.select_related("resident", "service_type").order_by("-request_date")[:2]:
        activity_items.append({
            "name": f"{service_request.resident.first_name} {service_request.resident.last_name}",
            "description": f"submitted a {service_request.service_type.name.lower()} request.",
            "timestamp": service_request.request_date,
            "avatar": f"{service_request.resident.first_name[:1]}{service_request.resident.last_name[:1]}".upper(),
        })

    activity_items = sorted(activity_items, key=lambda item: item["timestamp"], reverse=True)[:5]

    if not activity_items:
        fallback_now = timezone.now()
        activity_items = [
            {"name": "Walk Ignacio", "description": "was added as a new resident.", "timestamp": fallback_now, "avatar": "WI"},
            {"name": "Mary Santos", "description": "submitted a complaint about noise disturbance.", "timestamp": fallback_now, "avatar": "MS"},
            {"name": "Adrian Reyes", "description": "submitted a service request for street light repair.", "timestamp": fallback_now, "avatar": "AR"},
            {"name": "Anna Cruz", "description": "submitted a verification for approval.", "timestamp": fallback_now, "avatar": "AC"},
        ]

    service_type_counts = list(
        ServiceType.objects.annotate(total=Count("requests")).values("name", "total").order_by("-total", "name")[:5]
    )
    if service_type_counts:
        service_type_chart = [
            {"label": item["name"], "value": item["total"]}
            for item in service_type_counts
        ]
    else:
        service_type_chart = [
            {"label": "Clearance", "value": 12},
            {"label": "Indigency", "value": 10},
            {"label": "Residency", "value": 8},
            {"label": "Barangay ID", "value": 6},
            {"label": "Other", "value": 4},
        ]
    max_service_value = max(item["value"] for item in service_type_chart) or 1
    for item in service_type_chart:
        item["bar_height"] = max(26, round((item["value"] / max_service_value) * 110))

    monthly_labels = ["April", "May", "June", "July"]
    monthly_points = []
    for month_number, label in zip([4, 5, 6, 7], monthly_labels):
        monthly_points.append({
            "label": label,
            "value": ServiceRequest.objects.filter(
                request_date__year=today.year,
                request_date__month=month_number,
            ).count(),
        })
    if not any(point["value"] for point in monthly_points):
        monthly_points = [
            {"label": "April", "value": 18},
            {"label": "May", "value": 26},
            {"label": "June", "value": 31},
            {"label": "July", "value": 48},
        ]
    max_monthly_value = max(point["value"] for point in monthly_points) or 1
    monthly_coords = []
    x_positions = [28, 116, 204, 292]
    for index, point in enumerate(monthly_points):
        point["plot_y"] = 150 - round((point["value"] / max_monthly_value) * 96)
        monthly_coords.append(f"{x_positions[index]},{point['plot_y']}")

    male_count = Resident.objects.filter(gender="Male").count()
    female_count = Resident.objects.filter(gender="Female").count()
    gender_total = male_count + female_count
    if gender_total:
        male_percentage = round((male_count / gender_total) * 100)
        female_percentage = 100 - male_percentage
    else:
        male_percentage = 52
        female_percentage = 48
        male_count = 0
        female_count = 0

    context = {
        "kpis": kpis,
        "pending_actions": pending_actions,
        "activity_items": activity_items,
        "service_type_chart": service_type_chart,
        "service_request_chart_total": sum(item["value"] for item in service_type_chart),
        "monthly_points": monthly_points,
        "monthly_path": " ".join(monthly_coords),
        "monthly_requests_total": sum(point["value"] for point in monthly_points),
        "gender_stats": {
            "male": male_percentage,
            "female": female_percentage,
            "male_count": male_count,
            "female_count": female_count,
            "total": gender_total,
        },
        "secretary_name": (
            request.user.get_full_name().strip()
            or f"{request.user.first_name} {request.user.last_name}".strip()
            or "Joy Arcilla"
        ),
    }
    return render(request, 'secretary_dashboard.html', context)


#TREASURER DASHBOARD
#TREASURER DASHBOARD
#TREASURER DASHBOARD
@group_required(is_treasurer)
def treasurer_dashboard(request):

    today = timezone.now().date()
    month = today.month
    year = today.year

    # Paid clearances
    approved_requests = ServiceRequest.objects.filter(status="Ready for Release")
    payments = Payment.objects.all()

    context = {
    "approved_requests": approved_requests,
    "payments": payments
}

    total_revenue = payments.aggregate(total=Sum("amount"))["total"] or 0

    today_collections = payments.filter(
    payment_date=today
    ).aggregate(total=Sum("amount"))["total"] or 0

    monthly_collections = payments.filter(
    payment_date__month=month,
    payment_date__year = year
    ).aggregate(total=Sum("amount"))["total"] or 0

    recent_payments = payments.order_by("-payment_date")[:5]

    # NEW: Monthly revenue chart data
    monthly_data = (
        Payment.objects
        .filter(payment_date__year=year)
        .annotate(month=ExtractMonth("payment_date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )

    months = [m["month"] for m in monthly_data]
    totals = [float(m["total"]) for m in monthly_data]



    return render(request, "treasurer_dashboard.html", {
        "total_revenue": total_revenue,
        "today_collections": today_collections,
        "monthly_collections": monthly_collections,
        "recent_payments": recent_payments,
        "months": months,
        "totals": totals
    })

#STAFF DASHBOARD
#STAFF DASHBOARD
#STAFF DASHBOARD
@group_required(is_staff_group_user)
def staff_dashboard(request):
    return render(request, 'staff_dashboard.html')

#RESIDENT LIST
#RESIDENT LIST
#RESIDENT LIST
@group_required(is_staff_user)
def resident_list(request):

    query = request.GET.get("q", "").strip()
    gender = request.GET.get("gender", "").strip()
    status = request.GET.get("status", "").strip()

    all_residents = Resident.objects.select_related("household", "household__purok").all()
    residents = all_residents

    if query:
        residents = residents.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)  |
            Q(middle_name__icontains=query) 
        )
    if gender:
        residents = residents.filter(gender=gender)

    if status:
        residents = residents.filter(status=status)

    residents = residents.order_by("last_name", "first_name")

    context = {
        "residents": residents,
        "resident_total": all_residents.count(),
        "alive_total": all_residents.filter(status="Alive").count(),
        "voter_total": all_residents.filter(voter_status=True).count(),
        "senior_total": sum(1 for resident in all_residents if resident.age is not None and resident.age >= 60),
        "filtered_total": residents.count(),
    }

    return render(request, "resident_list.html", context)

#ADD RESIDENT
#ADD RESIDENT
#ADD RESIDENT
@group_required(is_secretary)
def add_resident(request):
    validation_errors = []
    tesseract_bin = _find_tesseract_binary()
    scan_support = {
        "ocr_ready": bool(tesseract_bin),
        "message": (
            "Full QR and text ID scanning is ready."
            if tesseract_bin
            else "QR-based ID scanning is ready. Install Tesseract later if you also want text-only IDs to auto-fill."
        ),
    }

    if request.method == 'POST':
        form = ResidentForm(request.POST)

        if form.is_valid():
            resident = form.save()

            log_audit_event(
                action="CREATE",
                model_name="Resident",
                description=f"Added resident {resident.first_name} {resident.last_name}",
                user=request.user,
                target_id=resident.id,
                after_data=snapshot_instance(resident),
                request=request,
            )

            return redirect('resident_list')
        for field_name in form.errors.keys():
            if field_name == "__all__":
                continue
            label = form.fields.get(field_name).label if form.fields.get(field_name) else field_name
            if label and label not in validation_errors:
                validation_errors.append(label)
        messages.error(request, "Please complete all required fields before saving.")

    else:
        form = ResidentForm()

    return render(request, 'residents/add_resident.html', {
        'form': form,
        'validation_errors': validation_errors,
        'scan_support': scan_support,
    })

#HOUSEHOLD
#HOUSEHOLD
#HOUSEHOLD
@group_required(is_staff_user)
def household_detail(request, pk):
    household = get_object_or_404(Household, pk=pk)

    members = household.members.all()

    total_members = members.count()
    voters = members.filter(voter_status=True).count()
    males = members.filter(gender="Male").count()
    females = members.filter(gender="Female").count()

    context = {
        "household": household,
        "members": members,
        "total_members": total_members,
        "voters": voters,
        "males": males,
        "females": females
    }

    return render(request, "household_detail.html", context)

#ADD RESIDENT TO HOUSEHOLD
#ADD RESIDENT TO HOUSEHOLD
#ADD RESIDENT TO HOUSEHOLD
@group_required(is_secretary)
def add_resident_to_household(request, household_id):
    household = get_object_or_404(Household, id=household_id)

    if request.method == "POST":
        form = ResidentForm(request.POST)
        if form.is_valid():
            resident = form.save(commit=False)
            resident.household = household
            resident.save()
            log_audit_event(
                action="UPDATE",
                model_name="Resident",
                description=f"Assigned resident {resident} to household {household.id}.",
                user=request.user,
                target_id=resident.id,
                after_data=snapshot_instance(resident),
                request=request,
            )
            return redirect("household_detail", pk=household.id)
    else:
        form = ResidentForm()

    return render(request, "residents/add_resident.html", {
        "form": form,
        "household": household
    })
#REMOVE FROM HOUSEHOLD
#REMOVE FROM HOUSEHOLD
#REMOVE FROM HOUSEHOLD
@group_required(is_secretary)
def remove_from_household(request, resident_id):
    resident = get_object_or_404(Resident, id=resident_id)

    before_data = snapshot_instance(resident)
    household = resident.household 

    resident.household = None
    resident.save()
    log_audit_event(
        action="UPDATE",
        model_name="Resident",
        description=f"Removed resident {resident} from household.",
        user=request.user,
        target_id=resident.id,
        before_data=before_data,
        after_data=snapshot_instance(resident),
        request=request,
    )

    if household:
        return redirect("household_detail", pk=household.id)

    return redirect("resident_list")

#HOUSEHOLD HEAD
#HOUSEHOLD HEAD
#HOUSEHOLD HEAD
@group_required(is_secretary)
def set_household_head(request, household_id, resident_id):
    household = get_object_or_404(Household, id=household_id)
    resident = get_object_or_404(Resident, id=resident_id)

    before_data = snapshot_instance(household)
    household.head = resident
    household.save()
    log_audit_event(
        action="UPDATE",
        model_name="Household",
        description=f"Set household {household.id} head to {resident}.",
        user=request.user,
        target_id=household.id,
        before_data=before_data,
        after_data=snapshot_instance(household),
        request=request,
    )

    return redirect("household_detail", pk=household.id)



#GENERATE CLEARANCE
#GENERATE CLEARANCE
#GENERATE CLEARANCE
@login_required
def create_service_request(request, resident_id):

    resident = get_object_or_404(Resident, id=resident_id)

    if not is_staff_user(request.user):
        if not is_resident(request.user):
            return HttpResponseForbidden("Only staff or resident accounts can create service requests.")
        profile = get_user_profile(request.user)
        if not profile or not profile.is_verified or not profile.resident:
            messages.error(request, "Only verified resident portal accounts can create service requests.")
            return redirect("portal_pending_verification")
        if profile.resident_id != resident.id:
            messages.error(request, "You can only create requests for your own linked resident record.")
            return redirect("portal_create_service_request")

    service_types = ServiceType.objects.order_by("name")
    service_purposes = RequestPurpose.objects.filter(is_active=True)

    def render_request_form():
        return render(
            request,
            "service_request_form.html",
            build_service_request_form_context(
                request,
                resident,
                service_types,
                service_purposes,
            ),
        )

    if request.method == "POST":
        service, context = handle_service_request_submission(
            request,
            resident,
            service_types,
            service_purposes,
        )
        if context is not None:
            return render(request, "service_request_form.html", context)
        return redirect("service_request_detail", request_id=service.id)

    return render_request_form()

#UPDATE SERVICE REQUEST STATUS
#UPDATE SERVICE REQUEST STATUS
#UPDATE SERVICE REQUEST STATUS
@group_required(is_staff_user)
def update_service_request_status(request, request_id):

    service_request = get_object_or_404(ServiceRequest, id=request_id)

    if not is_secretary(request.user):
        return HttpResponseForbidden("Only the Secretary can update service request statuses.")

    if request.method == "POST":

        new_status = request.POST.get("status")
        before_data = snapshot_instance(service_request)

        allowed_statuses = get_service_request_allowed_statuses(service_request.status)
        if new_status == service_request.status:
            messages.info(request, "This request is already in that status.")
            return redirect(request.META.get("HTTP_REFERER"))

        if new_status not in allowed_statuses:
            messages.error(request, "That status change is not allowed from the current workflow stage.")
            return redirect(request.META.get("HTTP_REFERER"))

        if new_status == "Pending Requirements":
            messages.error(request, "Use the requirements form so the resident can see exactly what to submit.")
            return redirect(request.META.get("HTTP_REFERER"))

        if new_status in dict(ServiceRequest.STATUS_CHOICES):
            service_request.status = new_status
            service_request.save()
            log_audit_event(
                action="UPDATE",
                model_name="ServiceRequest",
                description=f"Updated request {service_request.document_number} to {new_status}.",
                user=request.user,
                target_id=service_request.id,
                before_data=before_data,
                after_data=snapshot_instance(service_request),
                request=request,
            )
            notify_resident_for_service_request(
                service_request,
                title=f"Request {new_status}",
                message=f"Your {service_request.service_type.name} request is now marked as {new_status}.",
            )

    return redirect(request.META.get("HTTP_REFERER"))

#RESIDENT PROFILE
#RESIDENT PROFILE
#RESIDENT PROFILE
@login_required
def resident_profile(request, resident_id):
    resident = get_object_or_404(Resident, id=resident_id)
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident or profile.resident_id != resident.id:
            return HttpResponseForbidden("You can only view your own resident profile.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        services = ServiceRequest.objects.filter(resident=profile.resident)
    elif is_staff_user(request.user):
        services = ServiceRequest.objects.filter(resident=resident)
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")

    services = services.select_related("service_type").order_by("-request_date")

    status_filter = request.GET.get("status", "").strip()
    sort_filter = request.GET.get("sort", "newest").strip()

    valid_statuses = {choice[0] for choice in ServiceRequest.STATUS_CHOICES}
    if status_filter in valid_statuses:
        services = services.filter(status=status_filter)
    else:
        status_filter = ""

    if sort_filter == "oldest":
        services = services.order_by("request_date")
    elif sort_filter == "status":
        services = services.order_by("status", "-request_date")
    else:
        sort_filter = "newest"
        services = services.order_by("-request_date")

    all_services = ServiceRequest.objects.filter(resident=resident)

    context = {
        "resident": resident,
        "services": services,
        "total_requests": all_services.count(),
        "released_count": all_services.filter(status="Released").count(),
        "pending_count": all_services.filter(status__in=["Submitted", "Under Review", "For Validation", "Processing", "Pending Requirements", "On Hold"]).count(),
        "status_filter": status_filter,
        "sort_filter": sort_filter,
        "status_choices": ServiceRequest.STATUS_CHOICES,
    }
    return render(request, "resident_profile.html", context)


#EDIT RESIDENT
#EDIT RESIDENT
#EDIT RESIDENT
@group_required(is_secretary)
def edit_resident(request, resident_id):

    resident = get_object_or_404(Resident, id=resident_id)

    if request.method == "POST":
        before_data = snapshot_instance(resident)
        form = ResidentForm(request.POST, instance=resident)
        if form.is_valid():
            updated_resident = form.save()
            log_audit_event(
                action="UPDATE",
                model_name="Resident",
                description=f"Updated resident {resident.first_name} {resident.last_name}",
                user=request.user,
                target_id=resident.id,
                before_data=before_data,
                after_data=snapshot_instance(updated_resident),
                request=request,
            )
            
            return redirect("resident_profile", resident_id=resident.id)

    else:
        form = ResidentForm(instance=resident)

    return render(request, "edit_resident.html", {  
    "form": form,
    "resident": resident
})

#PAYMENT LIST
#PAYMENT LIST
#PAYMENT LIST
@group_required(is_treasurer)
def payment_list(request):

    # requests waiting for payment
    approved_requests = ServiceRequest.objects.filter(status="Ready for Release")

    # already paid
    payments = Payment.objects.all()

    return render(request, "payment_list.html", {
        "approved_requests": approved_requests,
        "payments": payments
    })

#RECORS PAYMENT
#RECORD PAYMENT
@group_required(is_treasurer)
def record_payment(request, request_id):
    if request.method != "POST":
        return redirect("payment_list")

    service_request = get_object_or_404(ServiceRequest, id=request_id)

    if service_request.status != "Ready for Release":
        messages.error(request, "Only requests marked ready for release can be paid at the cashier.")
        return redirect("payment_list")

    # prevent duplicate payments
    if Payment.objects.filter(service_request=service_request).exists():
        messages.warning(request, "Payment already exists for this request.")
        return redirect("payment_list")

    payment = Payment.objects.create(
        service_request=service_request,
        amount=service_request.fee,
        collected_by=request.user
    )
    log_audit_event(
        action="CREATE",
        model_name="Payment",
        description=f"Payment recorded for {service_request.resident}.",
        user=request.user,
        target_id=payment.id,
        after_data=snapshot_instance(payment),
        request=request,
    )

    notify_resident_for_service_request(
        service_request,
        title="Payment Recorded",
        message=f"Payment for your {service_request.service_type.name} request has been recorded.",
    )

    messages.success(request, "Payment recorded successfully.")
    return redirect("payment_list")

#ADD HOUSEHOLD
#ADD HOUSEHOLD
#ADD HOUSEHOLD
@login_required
@user_passes_test(is_secretary)
def add_household(request):

    if request.method == "POST":
        form = HouseholdForm(request.POST)

        if form.is_valid():
            household = form.save()
            log_audit_event(
                action="CREATE",
                model_name="Household",
                description=f"Added household {household.id}.",
                user=request.user,
                target_id=household.id,
                after_data=snapshot_instance(household),
                request=request,
            )
            return redirect("secretary_dashboard")

    else:
        form = HouseholdForm()

    return render(request, "add_household.html", {"form": form})

#HOUSEHOLD LIST
#HOUSEHOLD LIST
# HOUSEHOLD LIST
@group_required(is_staff_user)
def household_list(request):

    all_households = Household.objects.select_related("head", "purok").prefetch_related("members").all()
    households = all_households.order_by("purok", "house_number")

    purok = (request.GET.get("purok") or "").strip()
    search = (request.GET.get("q") or "").strip()

    if purok:
        households = households.filter(purok=purok)

    if search:
        households = households.filter(
            street__icontains=search
        )

    context = {
        "households": households,
        "filtered_total": households.count(),
        "total_households": all_households.count(),
        "total_residents": Resident.objects.filter(household__isnull=False).count(),
        "puroks": Purok.objects.order_by("name"),
    }

    return render(request, "household_list.html", context)

#COMPLAINT LIST     
#COMPLAINT LIST
#COMPLAINT LIST
@login_required
def complaint_list(request):
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident:
            return HttpResponseForbidden("Resident profile not linked.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        complaints = Complaint.objects.select_related("resident").filter(
            resident=profile.resident
        ).order_by("-date_filed")
    elif is_staff_user(request.user):
        complaints = Complaint.objects.select_related("resident").all().order_by("-date_filed")
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")

    all_complaints = complaints
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    if q:
        complaints = complaints.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(resident__first_name__icontains=q)
            | Q(resident__last_name__icontains=q)
        )

    if status:
        complaints = complaints.filter(status=status)

    return render(request, "complaint_list.html", {
        "complaints": complaints,
        "total_complaints": all_complaints.count(),
        "pending_count": all_complaints.filter(status__in=["Submitted", "Under Review"]).count(),
        "resolved_count": all_complaints.filter(status="Resolved / Settled").count(),
        "dismissed_count": all_complaints.filter(status="Withdrawn").count(),
        "for_mediation_count": all_complaints.filter(status__in=["For Scheduling", "Scheduled for Hearing", "Ongoing Mediation"]).count(),
        "filters": {
            "q": q,
            "status": status,
        },
        "status_choices": [choice[0] for choice in Complaint.STATUS_CHOICES],
        "is_resident_user": is_resident(request.user),
    })

#FILE COMPLAINT
#FILE COMPLAINT
#FILE COMPLAINT
@login_required
def file_complaint(request):
    resident_profile = None
    is_resident_user = is_resident(request.user)
    if is_resident_user:
        resident_profile = get_user_profile(request.user)
        if not resident_profile or not resident_profile.resident:
            messages.error(request, "Your resident profile is not linked yet.")
            return redirect("portal_pending_verification")
        if not resident_profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
    else:
        return HttpResponseForbidden("Only residents can submit complaints online.")

    if request.method == "POST":
        if is_resident_user:
            post_data = request.POST.copy()
            post_data["resident"] = str(resident_profile.resident_id)
            form = ComplaintForm(post_data)
        else:
            form = ComplaintForm(request.POST)

        if form.is_valid():
            complaint = form.save(commit=False)
            if is_resident_user:
                complaint.resident = resident_profile.resident
            complaint.filed_by = request.user
            complaint.save()

            log_audit_event(
                action="CREATE",
                model_name="Complaint",
                description=f"Complaint filed: {complaint.title}",
                user=request.user,
                target_id=complaint.id,
                after_data=snapshot_instance(complaint),
                request=request,
            )
            notify_resident_for_complaint(
                complaint,
                title="Complaint Submitted",
                message="Your complaint has been submitted online and is waiting for secretary review.",
            )
            notify_secretaries_of_complaint(complaint)
            return redirect("complaint_list")

    else:
        form = ComplaintForm()

    if is_resident_user:
        form.fields["resident"].widget = form.fields["resident"].hidden_widget()

    return render(request, "file_complaint.html", {
        "form": form,
        "is_resident_user": is_resident_user,
        "resident_profile": resident_profile,
    })

#COMPLAINT DETAIL
#COMPLAINT DETAIL
#COMPLAINT DETAIL
@login_required
def complaint_detail(request, complaint_id):

    complaint = get_object_or_404(Complaint.objects.select_related("resident__household__purok", "filed_by", "scheduled_by"), id=complaint_id)
    is_resident_viewer = False
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident or complaint.resident_id != profile.resident_id:
            return HttpResponseForbidden("You can only view your own complaints.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        can_manage = False
        is_resident_viewer = True
    elif is_staff_user(request.user):
        can_manage = is_secretary(request.user)
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")
    if can_manage and complaint.status == "Submitted":
        before_data = snapshot_instance(complaint)
        complaint.status = "Under Review"
        complaint.save(update_fields=["status", "updated_at"])
        log_audit_event(
            action="UPDATE",
            model_name="Complaint",
            description=f"Complaint '{complaint.title}' automatically moved to Under Review when opened by the Secretary.",
            user=request.user,
            target_id=complaint.id,
            before_data=before_data,
            after_data=snapshot_instance(complaint),
            request=request,
        )
        notify_resident_for_complaint(
            complaint,
            title="Complaint Under Review",
            message="Your complaint is now under review by the Secretary.",
        )
    primary_steps = [
        "Submitted",
        "Under Review",
        "For Scheduling",
        "Scheduled for Hearing",
        "Ongoing Mediation",
        "Resolved / Settled",
    ]
    progress_status = complaint.status if complaint.status in primary_steps else "Submitted"
    progress_index = primary_steps.index(progress_status)
    logs = AuditLog.objects.filter(model_name="Complaint", target_id=str(complaint.id)).select_related("user").order_by("timestamp")
    timeline_items = [{
        "title": "Complaint submitted",
        "description": f"{complaint.resident} submitted the complaint online.",
        "timestamp": complaint.date_filed,
        "actor": complaint.filed_by,
        "tone": "blue",
    }]
    for log in logs:
        timeline_items.append({
            "title": log.after_data.get("status") if log.after_data and log.after_data.get("status") else "Complaint updated",
            "description": log.description,
            "timestamp": log.timestamp,
            "actor": log.user,
            "tone": COMPLAINT_STATUS_COLORS.get((log.after_data or {}).get("status", ""), "sky"),
        })
    address_bits = []
    resident = complaint.resident
    if resident.household:
        if resident.household.house_number:
            address_bits.append(resident.household.house_number)
        if resident.household.street:
            address_bits.append(resident.household.street)
        if resident.household.purok:
            address_bits.append(f"Purok {resident.household.purok.name}")
    address_display = ", ".join(address_bits) if address_bits else "No household address recorded"
    next_statuses = COMPLAINT_STATUS_TRANSITIONS.get(complaint.status, [])
    resident_can_respond_to_schedule = (
        is_resident_viewer
        and complaint.status == "Scheduled for Hearing"
        and complaint.meeting_datetime is not None
        and complaint.resident_schedule_response != "Acknowledged"
    )
    resident_can_withdraw = (
        is_resident_viewer
        and complaint.status in {"Submitted", "Under Review", "For Scheduling", "Scheduled for Hearing"}
    )
    if complaint.resident_schedule_response == "Acknowledged":
        resident_response_help = "The hearing schedule has been acknowledged by the resident."
    elif complaint.resident_schedule_response == "Needs Reschedule":
        resident_response_help = "The resident asked the Secretary to review and adjust the hearing schedule."
    elif complaint.resident_schedule_response == "Cannot Attend":
        resident_response_help = "The resident informed the office that they cannot attend the current hearing schedule."
    else:
        resident_response_help = "The resident still needs to acknowledge the hearing schedule or request a change."
    return render(request, "complaint_detail.html", {
        "complaint": complaint,
        "can_manage": can_manage,
        "is_resident_viewer": is_resident_viewer,
        "primary_steps": primary_steps,
        "progress_index": progress_index,
        "timeline_items": timeline_items,
        "address_display": address_display,
        "next_statuses": next_statuses,
        "current_status_tone": COMPLAINT_STATUS_COLORS.get(complaint.status, "blue"),
        "schedule_response_tone": COMPLAINT_SCHEDULE_RESPONSE_COLORS.get(complaint.resident_schedule_response, "gold"),
        "resident_can_respond_to_schedule": resident_can_respond_to_schedule,
        "resident_can_withdraw": resident_can_withdraw,
        "resident_response_help": resident_response_help,
    })

#UPDATE COMPLAINT STATUS
#UPDATE COMPLAINT STATUS
#UPDATE COMPLAINT STATUS
@group_required(is_staff_user)
def update_complaint_status(request, complaint_id):

    complaint = get_object_or_404(Complaint, id=complaint_id)
    if not is_secretary(request.user):
        return HttpResponseForbidden("Only the Secretary can update complaint statuses.")

    if request.method == "POST":
        before_data = snapshot_instance(complaint)
        new_status = request.POST.get("status")
        if new_status not in COMPLAINT_STATUS_TRANSITIONS.get(complaint.status, []):
            messages.error(request, "That complaint status change is not allowed from the current stage.")
            return redirect("complaint_detail", complaint_id=complaint.id)
        complaint.status = new_status
        complaint.save()
        log_audit_event(
            action="UPDATE",
            model_name="Complaint",
            description=f"Complaint '{complaint.title}' updated to {new_status}",
            user=request.user,
            target_id=complaint.id,
            before_data=before_data,
            after_data=snapshot_instance(complaint),
            request=request,
        )
        notify_resident_for_complaint(
            complaint,
            title=f"Complaint {new_status}",
            message=f"Your complaint is now marked as {new_status}.",
        )

    return redirect("complaint_detail", complaint_id=complaint.id)


@group_required(is_staff_user)
def schedule_complaint_hearing(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)
    if not is_secretary(request.user):
        return HttpResponseForbidden("Only the Secretary can schedule complaint hearings.")
    if request.method != "POST":
        return redirect("complaint_detail", complaint_id=complaint.id)

    meeting_date = (request.POST.get("meeting_date") or "").strip()
    meeting_time = (request.POST.get("meeting_time") or "").strip()
    meeting_location = (request.POST.get("meeting_location") or "").strip()
    meeting_purpose = (request.POST.get("meeting_purpose") or "").strip()
    secretary_notes = (request.POST.get("secretary_notes") or "").strip()

    if not meeting_date or not meeting_time or not meeting_location or not meeting_purpose:
        messages.error(request, "Please complete the hearing date, time, location, and purpose.")
        return redirect("complaint_detail", complaint_id=complaint.id)

    scheduled_dt = timezone.make_aware(datetime.fromisoformat(f"{meeting_date}T{meeting_time}"))
    before_data = snapshot_instance(complaint)
    complaint.meeting_datetime = scheduled_dt
    complaint.meeting_location = meeting_location
    complaint.meeting_purpose = meeting_purpose
    complaint.secretary_notes = secretary_notes
    complaint.resident_schedule_response = "Pending Response"
    complaint.resident_schedule_responded_at = None
    complaint.resident_schedule_response_note = ""
    complaint.scheduled_by = request.user
    complaint.status = "Scheduled for Hearing"
    complaint.save()
    log_audit_event(
        action="UPDATE",
        model_name="Complaint",
        description=f"Scheduled hearing for complaint '{complaint.title}' on {scheduled_dt}.",
        user=request.user,
        target_id=complaint.id,
        before_data=before_data,
        after_data=snapshot_instance(complaint),
        request=request,
    )
    notify_resident_for_complaint(
        complaint,
        title="Hearing Scheduled",
        message=f"Your complaint hearing is scheduled on {scheduled_dt.strftime('%b %d, %Y at %I:%M %p')} at {meeting_location}. Purpose: {meeting_purpose}.",
    )
    messages.success(request, "Complaint hearing scheduled and resident notified.")
    return redirect("complaint_detail", complaint_id=complaint.id)


@group_required(lambda user: is_resident(user))
def respond_to_complaint_schedule(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)
    profile = get_user_profile(request.user)
    if not profile or not profile.resident or complaint.resident_id != profile.resident_id:
        return HttpResponseForbidden("You can only respond to your own complaint schedule.")
    if request.method != "POST":
        return redirect("complaint_detail", complaint_id=complaint.id)
    if complaint.status != "Scheduled for Hearing" or not complaint.meeting_datetime:
        messages.error(request, "There is no active hearing schedule to respond to.")
        return redirect("complaint_detail", complaint_id=complaint.id)
    if complaint.resident_schedule_response == "Acknowledged":
        messages.error(request, "You already acknowledged this hearing schedule and it can no longer be changed.")
        return redirect("complaint_detail", complaint_id=complaint.id)

    response_value = (request.POST.get("schedule_response") or "").strip()
    response_note = (request.POST.get("response_note") or "").strip()
    allowed_responses = {"Acknowledged", "Needs Reschedule", "Cannot Attend"}
    if response_value not in allowed_responses:
        messages.error(request, "Please choose a valid schedule response.")
        return redirect("complaint_detail", complaint_id=complaint.id)
    if response_value in {"Needs Reschedule", "Cannot Attend"} and not response_note:
        messages.error(request, "Please provide a short note so the Secretary understands your request.")
        return redirect("complaint_detail", complaint_id=complaint.id)

    before_data = snapshot_instance(complaint)
    complaint.resident_schedule_response = response_value
    complaint.resident_schedule_responded_at = timezone.now()
    complaint.resident_schedule_response_note = response_note
    complaint.save()

    log_audit_event(
        action="UPDATE",
        model_name="Complaint",
        description=f"Resident responded to the hearing schedule: {response_value}.",
        user=request.user,
        target_id=complaint.id,
        before_data=before_data,
        after_data=snapshot_instance(complaint),
        request=request,
    )

    notify_resident_for_complaint(
        complaint,
        title=f"Schedule {response_value}",
        message=(
            "You acknowledged the hearing schedule."
            if response_value == "Acknowledged"
            else f"Your response to the hearing schedule was sent to the Secretary: {response_value}."
        ),
    )
    messages.success(request, "Your schedule response has been recorded.")
    return redirect("complaint_detail", complaint_id=complaint.id)


@group_required(lambda user: is_resident(user))
def withdraw_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)
    profile = get_user_profile(request.user)
    if not profile or not profile.resident or complaint.resident_id != profile.resident_id:
        return HttpResponseForbidden("You can only withdraw your own complaint.")
    if request.method != "POST":
        return redirect("complaint_detail", complaint_id=complaint.id)
    if complaint.status not in {"Submitted", "Under Review", "For Scheduling", "Scheduled for Hearing"}:
        messages.error(request, "This complaint can no longer be withdrawn from the resident side.")
        return redirect("complaint_detail", complaint_id=complaint.id)

    before_data = snapshot_instance(complaint)
    complaint.status = "Withdrawn"
    complaint.save()
    log_audit_event(
        action="UPDATE",
        model_name="Complaint",
        description=f"Resident withdrew complaint '{complaint.title}'.",
        user=request.user,
        target_id=complaint.id,
        before_data=before_data,
        after_data=snapshot_instance(complaint),
        request=request,
    )
    messages.success(request, "Your complaint has been withdrawn.")
    return redirect("complaint_detail", complaint_id=complaint.id)

#EXPORT RESDIENTS CSV
#EXPORT RESDIENTS CSV
#EXPORT RESIDENTS CSV
@login_required
@user_passes_test(is_captain)
def export_residents_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="residents_report.csv"'

    writer = csv.writer(response)

    # Header row
    writer.writerow([
        "First Name",
        "Last Name",
        "Gender",
        "Birth Date",
        "Civil Status",
        "Voter Status",
        "Resident Status",
        "Purok"
    ])

    residents = Resident.objects.select_related("household").all()

    for resident in residents:

        purok = resident.household.purok if resident.household else "N/A"

        writer.writerow([
            resident.first_name,
            resident.last_name,
            resident.gender,
            resident.birth_date,
            resident.civil_status,
            resident.voter_status,
            resident.status,
            purok
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Resident",
        description=f"Exported residents CSV ({residents.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT PAYMENTS CSV
#EXPORT PAYMENTS CSV
#EXPORT PAYMENTS CSV
@group_required(is_staff_user)
def export_payments_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="payments_report.csv"'

    writer = csv.writer(response)

    # Header
    writer.writerow([
        "Receipt Number",
        "Resident",
        "Service",
        "Amount",
        "Payment Date",
        "Collected By"
    ])

    payments = Payment.objects.select_related(
        "service_request__resident"
    ).all()

    for payment in payments:

        writer.writerow([
            payment.receipt_number,
            payment.service_request.resident,
            payment.service_request.service_type,
            payment.amount,
            payment.payment_date,
            payment.collected_by
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Payment",
        description=f"Exported payments CSV ({payments.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT HOUSEHOLDS CSV
#EXPORT HOUSEHOLDS CSV
#EXPORT HOUSEHOLDS CSV
@login_required
@user_passes_test(is_captain)
def export_households_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="households_report.csv"'

    writer = csv.writer(response)

    writer.writerow([
        "Household ID",
        "Household Head",
        "Purok",
        "Total Members"
    ])

    households = Household.objects.all()

    for household in households:

        head = household.head if household.head else "None"
        members = household.members.count()

        writer.writerow([
            household.id,
            head,
            household.purok,
            members
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Household",
        description=f"Exported households CSV ({households.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT COMPLAINTS CSV
#EXPORT COMPLAINTS CSV
#EXPORt COMPLAINTS CSV
@login_required
@user_passes_test(is_captain)
def export_complaints_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="complaints_report.csv"'

    writer = csv.writer(response)

    writer.writerow([
        "Complaint Title",
        "Resident",
        "Description",
        "Status",
        "Date Filed"
    ])

    complaints = Complaint.objects.select_related("resident").all()

    for complaint in complaints:

        writer.writerow([
            complaint.title,
            complaint.resident,
            complaint.description,
            complaint.status,
            complaint.date_filed
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Complaint",
        description=f"Exported complaints CSV ({complaints.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT BARANGAY SUMMARY CSV
#EXPORT BARANGAY SUMMARY CSV
#EXPORT BARANGAY SUMMARY CSV
@login_required
@user_passes_test(is_captain)
def export_barangay_summary_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="barangay_summary_report.csv"'

    writer = csv.writer(response)

    writer.writerow(["Barangay Summary Report"])
    writer.writerow([])

    total_residents = Resident.objects.count()
    total_households = Household.objects.count()
    total_complaints = Complaint.objects.count()
    documents_issued = ServiceRequest.objects.count()

    total_revenue = Payment.objects.aggregate(
    total=Sum("amount")
    )["total"] or 0

    writer.writerow(["Total Residents", total_residents])
    writer.writerow(["Total Households", total_households])
    writer.writerow(["Total Complaints", total_complaints])
    writer.writerow(["Documents Issued", documents_issued])
    writer.writerow(["Total Revenue", total_revenue])
    log_audit_event(
        action="EXPORT",
        model_name="BarangaySummary",
        description="Exported barangay summary CSV report.",
        user=request.user,
        request=request,
    )

    return response



#Generate_Document
#Generate_Document
#Generate_Document

def _render_service_request_document(request, service):
    resident = service.resident
    address = "-"
    if resident.household:
        address = f"{resident.household.house_number} {resident.household.street}"

    # Decide which template to load
    service_name = service.service_type.name.lower()
    if "clearance" in service_name:
        template = "clearance_print.html"

    elif "residency" in service_name:
        template = "residency_print.html"

    elif "indigency" in service_name:
        template = "indigency_print.html"

    elif "qcid" in service_name or "qc id" in service_name:
        template = "qcid_print.html"

    elif "barangay id" in service_name:
        template = "barangay_id_print.html"

    else:
        template = "clearance_print.html"

    context = {
        "service": service,
        "resident": resident,
        "address": address,
        "today": date.today(),
    }
    return render(request, template, context)


@group_required(is_staff_user)
def generate_document(request, request_id):

    service = get_object_or_404(ServiceRequest, id=request_id)

    log_audit_event(
        action="PRINT",
        model_name="ServiceRequest",
        description=f"Generated document for request {service.document_number}.",
        user=request.user,
        target_id=service.id,
        request=request,
    )

    return _render_service_request_document(request, service)


@group_required(is_staff_user)
def print_and_release_document(request, request_id):

    service = get_object_or_404(ServiceRequest, id=request_id)

    if not is_secretary(request.user):
        return HttpResponseForbidden("Only the Secretary can release service requests.")

    if service.status not in {"Ready for Release", "Released"}:
        messages.error(request, "Only requests marked ready for release can be released.")
        return redirect("service_requests")

    if service.status == "Ready for Release":
        before_data = snapshot_instance(service)
        service.status = "Released"
        service.save()
        log_audit_event(
            action="UPDATE",
            model_name="ServiceRequest",
            description=f"Request {service.document_number} was printed and released.",
            user=request.user,
            target_id=service.id,
            before_data=before_data,
            after_data=snapshot_instance(service),
            request=request,
        )
        notify_resident_for_service_request(
            service,
            title="Request Released",
            message=f"Your {service.service_type.name} request has been released successfully.",
        )

    log_audit_event(
        action="PRINT",
        model_name="ServiceRequest",
        description=f"Printed document for request {service.document_number}.",
        user=request.user,
        target_id=service.id,
        request=request,
    )

    return _render_service_request_document(request, service)

# SERVICE REQUEST LIST
# SERVICE REQUEST LIST
# SERVICE REQUEST LIST
@login_required
def service_request_detail(request, request_id):
    service_request = get_object_or_404(
        ServiceRequest.objects.select_related(
            "resident__household__purok",
            "service_type",
            "created_by",
            "requirements_requested_by",
        ).prefetch_related("attachments__uploaded_by"),
        id=request_id,
    )

    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident or profile.resident_id != service_request.resident_id:
            return HttpResponseForbidden("You can only view your own request details.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
    elif not is_staff_user(request.user):
        return HttpResponseForbidden("You do not have permission to access this page.")

    can_manage = is_secretary(request.user)
    is_resident_user = is_resident(request.user)

    requirement_initial = {
        "requirements_note": service_request.requirements_note,
        "requirements_submission_instructions": service_request.requirements_submission_instructions,
        "requirements_deadline": service_request.requirements_deadline,
    }
    resident_initial = {
        "resident_response_note": service_request.resident_response_note,
    }
    requirement_form = ServiceRequestRequirementsForm(initial=requirement_initial)
    resident_submission_form = ServiceRequestResidentSubmissionForm(initial=resident_initial)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "request_requirements":
            if not can_manage:
                return HttpResponseForbidden("Only the Secretary can request additional requirements.")
            if service_request.status not in {"Under Review", "Pending Requirements"}:
                messages.error(request, "Requirements can only be requested while the service request is under review.")
                return redirect("service_request_detail", request_id=service_request.id)

            requirement_form = ServiceRequestRequirementsForm(request.POST)
            if requirement_form.is_valid():
                is_updating_existing_request = service_request.status == "Pending Requirements" and bool(
                    service_request.requirements_requested_at
                )
                before_data = snapshot_instance(service_request)
                service_request.requirements_note = requirement_form.cleaned_data["requirements_note"]
                service_request.requirements_submission_instructions = requirement_form.cleaned_data["requirements_submission_instructions"]
                service_request.requirements_deadline = requirement_form.cleaned_data["requirements_deadline"]
                service_request.requirements_requested_at = timezone.now()
                service_request.requirements_requested_by = request.user
                service_request.status = "Pending Requirements"
                service_request.save()
                log_audit_event(
                    action="UPDATE",
                    model_name="ServiceRequest",
                    description=(
                        f"Updated the active requirements request for {service_request.document_number}."
                        if is_updating_existing_request
                        else f"Requested additional requirements for {service_request.document_number}."
                    ),
                    user=request.user,
                    target_id=service_request.id,
                    before_data=before_data,
                    after_data=snapshot_instance(service_request),
                    request=request,
                )
                notify_resident_for_service_request(
                    service_request,
                    title="Requirements Request Updated" if is_updating_existing_request else "Additional Requirements Needed",
                    message=(
                        f"The Secretary updated the missing requirements for your {service_request.service_type.name} request."
                        if is_updating_existing_request
                        else f"The Secretary sent the missing requirements for your {service_request.service_type.name} request."
                    ),
                )
                messages.success(
                    request,
                    "The active requirements request was updated."
                    if is_updating_existing_request
                    else "The missing requirements were sent to the resident.",
                )
                return redirect("service_request_detail", request_id=service_request.id)

        elif action == "submit_requirements":
            if not is_resident_user:
                return HttpResponseForbidden("Only the resident can submit requirement files for this request.")
            if service_request.status != "Pending Requirements":
                messages.error(request, "This request is not currently waiting for resident requirements.")
                return redirect("service_request_detail", request_id=service_request.id)

            resident_submission_form = ServiceRequestResidentSubmissionForm(request.POST)
            uploaded_files = request.FILES.getlist("requirement_files")
            if resident_submission_form.is_valid():
                response_note = resident_submission_form.cleaned_data["resident_response_note"].strip()
                if not response_note and not uploaded_files:
                    resident_submission_form.add_error("resident_response_note", "Add a short note or upload at least one file.")
                else:
                    before_data = snapshot_instance(service_request)
                    service_request.resident_response_note = response_note
                    service_request.resident_responded_at = timezone.now()
                    service_request.status = "Under Review"
                    service_request.save()
                    for uploaded_file in uploaded_files:
                        ServiceRequestAttachment.objects.create(
                            service_request=service_request,
                            uploaded_by=request.user,
                            file=uploaded_file,
                            original_name=uploaded_file.name,
                            note=response_note[:255],
                        )
                    log_audit_event(
                        action="UPDATE",
                        model_name="ServiceRequest",
                        description=f"Resident submitted additional requirements for {service_request.document_number}.",
                        user=request.user,
                        target_id=service_request.id,
                        before_data=before_data,
                        after_data=snapshot_instance(service_request),
                        request=request,
                    )
                    notify_resident_for_service_request(
                        service_request,
                        title="Requirements Submitted",
                        message=f"Your additional files for the {service_request.service_type.name} request were submitted to the Secretary.",
                    )
                    messages.success(request, "Your files and note were submitted. The request is back under review.")
                    return redirect("service_request_detail", request_id=service_request.id)

    status_history = get_service_request_status_history(service_request)
    progress_status = get_service_request_progress_status(service_request.status)
    progress_index = SERVICE_REQUEST_PRIMARY_STEPS.index(progress_status)
    latest_secretary_log = (
        AuditLog.objects.filter(
            model_name="ServiceRequest",
            target_id=str(service_request.id),
            user__groups__name="Secretary",
        )
        .select_related("user")
        .order_by("-timestamp")
        .first()
    )

    resident = service_request.resident
    address_bits = []
    if resident.household:
        if resident.household.house_number:
            address_bits.append(resident.household.house_number)
        if resident.household.street:
            address_bits.append(resident.household.street)
        if resident.household.purok:
            address_bits.append(f"Purok {resident.household.purok.name}")
    address_display = ", ".join(address_bits) if address_bits else "No household address recorded"

    timeline_items = []
    timeline_items.append({
        "title": "Request submitted",
        "meta": service_request.request_date,
        "description": f"{resident} submitted a {service_request.service_type.name} request.",
        "actor": service_request.created_by,
        "tone": "blue",
    })
    for item in status_history[1:]:
        timeline_items.append({
            "title": item["status"],
            "meta": item["timestamp"],
            "description": item["description"],
            "actor": item["actor"],
            "tone": SERVICE_REQUEST_STATUS_COLORS.get(item["status"], "blue"),
        })
    if service_request.requirements_requested_at and service_request.requirements_note:
        timeline_items.append({
            "title": "Additional requirements requested",
            "meta": service_request.requirements_requested_at,
            "description": service_request.requirements_note,
            "actor": service_request.requirements_requested_by,
            "tone": "gold",
        })
    if service_request.resident_responded_at:
        response_parts = []
        if service_request.resident_response_note:
            response_parts.append(service_request.resident_response_note)
        attachment_count = service_request.attachments.count()
        if attachment_count:
            response_parts.append(f"{attachment_count} file(s) uploaded.")
        timeline_items.append({
            "title": "Resident submitted requirements",
            "meta": service_request.resident_responded_at,
            "description": " ".join(response_parts) if response_parts else "The resident submitted the requested requirements.",
            "actor": resident,
            "tone": "teal",
        })
    timeline_items.sort(key=lambda item: item["meta"])

    current_handler_name = "Secretary Workspace"
    if latest_secretary_log and latest_secretary_log.user:
        current_handler_name = latest_secretary_log.user.get_full_name() or latest_secretary_log.user.username

    last_status_entry = status_history[-1] if status_history else None
    elapsed_days = max((timezone.now() - service_request.request_date).days, 0)
    can_print_release = is_secretary(request.user) and service_request.status == "Ready for Release"
    allowed_statuses = get_service_request_allowed_statuses(service_request.status)
    non_requirement_statuses = [status for status in allowed_statuses if status != "Pending Requirements"]
    next_step = non_requirement_statuses[0] if non_requirement_statuses else None
    has_active_requirement_request = (
        service_request.status == "Pending Requirements"
        and bool(service_request.requirements_requested_at and service_request.requirements_note)
    )
    is_editing_requirement_request = (
        can_manage
        and request.GET.get("edit_requirements") == "1"
        and service_request.status == "Pending Requirements"
    )
    resident_action_text = None
    if service_request.status == "Pending Requirements":
        resident_action_text = "Resident action required: submit the missing information or documents so processing can continue."
    elif service_request.status == "Ready for Release":
        resident_action_text = "Resident may prepare for pickup. The Secretary can now release the finished document."

    notification_items = [
        {
            "title": "Request Received",
            "message": f"Your {service_request.service_type.name} request was submitted successfully.",
            "timestamp": service_request.request_date,
            "tone": "blue",
        }
    ]
    if service_request.status in {"Under Review", "For Validation", "Processing"}:
        notification_items.append({
            "title": "Processing Update",
            "message": f"Your request is now {service_request.status.lower()} by the Secretary.",
            "timestamp": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
            "tone": "sky" if service_request.status == "Under Review" else "violet" if service_request.status == "For Validation" else "teal",
        })
    elif service_request.status == "Pending Requirements":
        notification_items.append({
            "title": "Action Needed",
            "message": service_request.requirements_note or "Please submit the missing requirements so the Secretary can continue processing your request.",
            "timestamp": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
            "tone": "gold",
        })
    elif service_request.status == "On Hold":
        notification_items.append({
            "title": "Request On Hold",
            "message": "Your request is temporarily on hold while records or details are being checked.",
            "timestamp": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
            "tone": "orange",
        })
    elif service_request.status == "Ready for Release":
        notification_items.append({
            "title": "Ready for Release",
            "message": "Your document is ready for pickup. Please wait for release confirmation from the Secretary.",
            "timestamp": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
            "tone": "amber",
        })
    elif service_request.status == "Released":
        notification_items.append({
            "title": "Released",
            "message": "Your document has been released successfully.",
            "timestamp": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
            "tone": "green",
        })
    elif service_request.status == "Rejected":
        notification_items.append({
            "title": "Request Rejected",
            "message": "Your request could not be processed. Please contact the barangay office for guidance.",
            "timestamp": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
            "tone": "red",
        })
    elif service_request.status == "Cancelled":
        notification_items.append({
            "title": "Request Cancelled",
            "message": "This request has been cancelled and closed.",
            "timestamp": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
            "tone": "slate",
        })

    context = {
        "service_request": service_request,
        "resident": resident,
        "address_display": address_display,
        "primary_steps": SERVICE_REQUEST_PRIMARY_STEPS,
        "progress_status": progress_status,
        "progress_index": progress_index,
        "status_history": status_history,
        "timeline_items": timeline_items,
        "current_handler_name": current_handler_name,
        "last_updated_at": latest_secretary_log.timestamp if latest_secretary_log else service_request.request_date,
        "current_stage_since": last_status_entry["timestamp"] if last_status_entry else service_request.request_date,
        "estimated_processing_text": SERVICE_REQUEST_ESTIMATES.get(service_request.status, "Processing time will depend on request completeness."),
        "elapsed_days": elapsed_days,
        "allowed_statuses": non_requirement_statuses,
        "next_step": next_step,
        "resident_action_text": resident_action_text,
        "notification_items": notification_items,
        "current_status_tone": SERVICE_REQUEST_STATUS_COLORS.get(service_request.status, "blue"),
        "can_manage": can_manage,
        "can_print_release": can_print_release,
        "is_view_only": not can_manage,
        "requirement_form": requirement_form,
        "resident_submission_form": resident_submission_form,
        "requirement_attachments": service_request.attachments.all(),
        "can_request_requirements": can_manage and service_request.status in {"Under Review", "Pending Requirements"},
        "has_active_requirement_request": has_active_requirement_request,
        "show_requirement_request_form": can_manage and (
            service_request.status == "Under Review" or is_editing_requirement_request
        ),
        "is_editing_requirement_request": is_editing_requirement_request,
        "can_submit_requirements": is_resident_user and service_request.status == "Pending Requirements",
    }
    return render(request, "service_request_detail.html", context)


@login_required
def resident_notifications(request):
    if not is_resident(request.user):
        return HttpResponseForbidden("Only resident accounts can access notifications.")

    profile = get_user_profile(request.user)
    if not profile or not profile.is_verified:
        messages.error(request, "Your account is still pending verification.")
        return redirect("portal_pending_verification")

    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "resident_notifications.html", {
        "notifications": notifications,
    })


@login_required
def open_notification(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return redirect(notification.target_url or "resident_notifications")


@login_required
def mark_all_notifications_read(request):
    if request.method != "POST":
        return redirect("resident_notifications")
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("resident_notifications")


@login_required
def service_requests(request):
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident:
            return HttpResponseForbidden("Resident profile not linked.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        requests = ServiceRequest.objects.select_related(
            "resident", "service_type"
        ).filter(
            resident=profile.resident
        ).annotate(
            has_payment=Count("payment")
        ).order_by("-request_date")
    elif is_staff_user(request.user):
        requests = ServiceRequest.objects.select_related(
            "resident", "service_type"
        ).annotate(
            has_payment=Count("payment")
        ).order_by("-request_date")
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")

    query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if query:
        requests = requests.filter(
            Q(document_number__icontains=query)
            | Q(resident__first_name__icontains=query)
            | Q(resident__last_name__icontains=query)
            | Q(service_type__name__icontains=query)
            | Q(purpose__icontains=query)
        )
    if status_filter in dict(ServiceRequest.STATUS_CHOICES):
        requests = requests.filter(status=status_filter)
    else:
        status_filter = ""

    request_list = list(requests)
    for item in request_list:
        item.allowed_statuses = get_service_request_allowed_statuses(item.status)

    return render(request, "service_requests.html", {
        "requests": request_list,
        "submitted_total": sum(1 for item in request_list if item.status == "Submitted"),
        "review_total": sum(1 for item in request_list if item.status == "Under Review"),
        "validation_total": sum(1 for item in request_list if item.status == "For Validation"),
        "processing_total": sum(1 for item in request_list if item.status == "Processing"),
        "ready_total": sum(1 for item in request_list if item.status == "Ready for Release"),
        "released_total": sum(1 for item in request_list if item.status == "Released"),
        "status_choices": ServiceRequest.STATUS_CHOICES,
        "q": query,
        "status_filter": status_filter,
        "can_manage_requests": is_secretary(request.user),
    })

@login_required
@user_passes_test(is_captain)
def audit_logs(request):
    logs = AuditLog.objects.select_related("user").all()
    users = User.objects.filter(is_active=True).order_by("username")
    models = AuditLog.objects.values_list("model_name", flat=True).distinct().order_by("model_name")

    action = request.GET.get("action", "").strip()
    model_name = request.GET.get("model_name", "").strip()
    user_id = request.GET.get("user_id", "").strip()
    q = request.GET.get("q", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    if action:
        logs = logs.filter(action=action)
    if model_name:
        logs = logs.filter(model_name=model_name)
    if user_id:
        logs = logs.filter(user_id=user_id)
    if start_date:
        logs = logs.filter(timestamp__date__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__date__lte=end_date)
    if q:
        logs = logs.filter(
            Q(description__icontains=q)
            | Q(target_id__icontains=q)
            | Q(user__username__icontains=q)
        )

    return render(request, "audit_logs.html", {
        "logs": logs,
        "users": users,
        "models": models,
        "actions": AuditLog.ACTION_CHOICES,
        "filters": {
            "action": action,
            "model_name": model_name,
            "user_id": user_id,
            "q": q,
            "start_date": start_date,
            "end_date": end_date,
        },
    })
