from django.db import migrations


PORTAL_SERVICE_TYPE_NAMES = [
    "Barangay Clearance",
    "Certificate of Residency",
    "REQUEST FIRST TIME JOBSEEKER",
    "Business Clearance",
    "Barangay Permit",
    "Solo Parent Certificate",
    "Senior Citizen Certificate",
    "CERTIFICATE OF INDIGENCY",
    "Medical Assistance Certification",
    "Scholarship Assistance Certification",
    "BRGY ID APPLICATION FORM",
    "Solo Parent ID Endorsement",
    "QCID Assistance",
    "Proof of Residency for ID",
]

LEGACY_FEE_SOURCES = {
    "Barangay Clearance": "Service Request",
    "Certificate of Residency": "Service Request",
    "REQUEST FIRST TIME JOBSEEKER": "Service Request",
    "Barangay Permit": "Service Request",
    "Solo Parent Certificate": "Service Request",
    "Senior Citizen Certificate": "Service Request",
    "Business Clearance": "Business Clearance",
    "CERTIFICATE OF INDIGENCY": "Indigency",
    "Medical Assistance Certification": "Indigency",
    "Scholarship Assistance Certification": "Indigency",
    "BRGY ID APPLICATION FORM": "Barangay ID",
    "Solo Parent ID Endorsement": "Barangay ID",
    "QCID Assistance": "QCID",
    "Proof of Residency for ID": "QCID",
}


def seed_portal_service_types(apps, schema_editor):
    ServiceType = apps.get_model("residents", "ServiceType")

    for service_name in PORTAL_SERVICE_TYPE_NAMES:
        existing = ServiceType.objects.filter(name=service_name).first()
        if existing:
            continue

        legacy_name = LEGACY_FEE_SOURCES.get(service_name)
        legacy = ServiceType.objects.filter(name=legacy_name).first() if legacy_name else None

        ServiceType.objects.create(
            name=service_name,
            fee=legacy.fee if legacy else 0,
            voter_fee=legacy.voter_fee if legacy else 0,
            non_voter_fee=legacy.non_voter_fee if legacy else 0,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0036_remove_household_purok_delete_purok"),
    ]

    operations = [
        migrations.RunPython(seed_portal_service_types, migrations.RunPython.noop),
    ]
