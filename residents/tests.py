import shutil
from datetime import timedelta
from pathlib import Path
import re

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import ComplaintForm, HouseholdForm, ResidentPortalRegistrationForm
from .models import Complaint, Notification, Resident, ServiceRequest, ServiceType, UserProfile
from .views import (
    get_portal_services,
    notify_resident_for_service_request,
    notify_secretaries_of_complaint,
    notify_secretaries_of_service_request,
)


TEST_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
    b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


TEST_MEDIA_ROOT = Path(__file__).resolve().parent.parent / "test_media"


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ResidentPortalRegistrationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_registration_saves_address_and_valid_id(self):
        response = self.client.post(
            reverse("resident_register"),
            data={
                "username": "juanresident",
                "first_name": "Juan",
                "middle_name": "Santos",
                "last_name": "Dela Cruz",
                "suffix": "",
                "birthdate": "2000-01-15",
                "place_of_birth": "Quezon City",
                "gender": "Male",
                "civil_status": "Single",
                "nationality": "Filipino",
                "religion": "Catholic",
                "occupation": "Student",
                "educational_attainment": "College",
                "contact_number": "09123456789",
                "email": "juanresident@example.com",
                "permanent_address": "True",
                "address_house_number": "123",
                "address_street": "Sampaguita St.",
                "address_barangay": "",
                "address_city": "",
                "address_province": "",
                "precinct": "101A",
                "pwd": "",
                "indigenous": "",
                "solo_parent": "",
                "voter_status": "on",
                "status": "Alive",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "valid_id_image": SimpleUploadedFile(
                    "valid-id.gif",
                    TEST_GIF,
                    content_type="image/gif",
                ),
            },
        )

        self.assertRedirects(response, reverse("portal_pending_verification"))
        profile = UserProfile.objects.get(user__username="juanresident")
        self.assertEqual(profile.address, "123, Sampaguita St., Gulod, Quezon City, Metro Manila")
        self.assertEqual(profile.middle_name, "Santos")
        self.assertEqual(profile.gender, "Male")
        self.assertTrue(bool(profile.valid_id_image))

    def test_secretary_can_view_uploaded_id_in_pending_verifications(self):
        resident_group, _ = Group.objects.get_or_create(name="Resident")
        secretary_group, _ = Group.objects.get_or_create(name="Secretary")

        resident_user = User.objects.create_user(
            username="pendingresident",
            password="StrongPass123!",
        )
        resident_user.groups.add(resident_group)
        UserProfile.objects.create(
            user=resident_user,
            first_name="Maria",
            last_name="Santos",
            birth_date="1998-05-10",
            address="Blk 2 Lot 5 Gulod",
            valid_id_image=SimpleUploadedFile(
                "valid-id.gif",
                TEST_GIF,
                content_type="image/gif",
            ),
        )

        secretary_user = User.objects.create_user(
            username="secretary1",
            password="StrongPass123!",
        )
        secretary_user.groups.add(secretary_group)

        self.client.login(username="secretary1", password="StrongPass123!")
        response = self.client.get(reverse("pending_verifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Blk 2 Lot 5 Gulod")
        self.assertContains(response, "View uploaded ID")

    def test_pending_verification_page_renders_uploaded_id_image(self):
        response = self.client.post(
            reverse("resident_register"),
            data={
                "username": "idalive",
                "first_name": "Ida",
                "middle_name": "Mae",
                "last_name": "Live",
                "suffix": "",
                "birthdate": "2001-03-21",
                "place_of_birth": "Quezon City",
                "gender": "Female",
                "civil_status": "Single",
                "nationality": "Filipino",
                "religion": "Catholic",
                "occupation": "Student",
                "educational_attainment": "College",
                "contact_number": "09123456789",
                "email": "idalive@example.com",
                "permanent_address": "False",
                "address_house_number": "45",
                "address_street": "Mabini Street",
                "address_barangay": "Bagbag",
                "address_city": "Quezon City",
                "address_province": "Metro Manila",
                "precinct": "202B",
                "pwd": "",
                "indigenous": "",
                "solo_parent": "",
                "voter_status": "",
                "status": "Alive",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "valid_id_image": SimpleUploadedFile(
                    "valid-id.gif",
                    TEST_GIF,
                    content_type="image/gif",
                ),
            },
        )

        self.assertRedirects(response, reverse("portal_pending_verification"))
        response = self.client.get(reverse("portal_pending_verification"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/media/valid_ids/")

    def test_registration_rejects_invalid_email_phone_and_weak_password(self):
        form = ResidentPortalRegistrationForm(
            data={
                "username": "weakresident",
                "first_name": "Juan",
                "last_name": "Dela Cruz",
                "birthdate": "2000-01-15",
                "gender": "Male",
                "civil_status": "Single",
                "contact_number": "09AB3456789",
                "email": "invalid-email",
                "permanent_address": "True",
                "password1": "weakpass",
                "password2": "weakpass",
            },
            files={
                "valid_id_image": SimpleUploadedFile(
                    "valid-id.gif",
                    TEST_GIF,
                    content_type="image/gif",
                ),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertIn("contact_number", form.errors)
        self.assertIn("password1", form.errors)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
    )
    def test_registration_emails_all_secretaries_with_email_addresses(self):
        secretary_group, _ = Group.objects.get_or_create(name="Secretary")

        secretary_one = User.objects.create_user(
            username="secretary_email_1",
            email="secretary1@example.com",
            password="StrongPass123!",
        )
        secretary_one.groups.add(secretary_group)

        secretary_two = User.objects.create_user(
            username="secretary_email_2",
            email="secretary2@example.com",
            password="StrongPass123!",
        )
        secretary_two.groups.add(secretary_group)

        secretary_without_email = User.objects.create_user(
            username="secretary_no_email",
            email="",
            password="StrongPass123!",
        )
        secretary_without_email.groups.add(secretary_group)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("resident_register"),
                data={
                    "username": "juanresidentmail",
                    "first_name": "Juan",
                    "middle_name": "Santos",
                    "last_name": "Dela Cruz",
                    "suffix": "",
                    "birthdate": "2000-01-15",
                    "place_of_birth": "Quezon City",
                    "gender": "Male",
                    "civil_status": "Single",
                    "nationality": "Filipino",
                    "religion": "Catholic",
                    "occupation": "Student",
                    "educational_attainment": "College",
                    "contact_number": "09123456789",
                    "email": "juanresidentmail@example.com",
                    "permanent_address": "True",
                    "address_house_number": "123",
                    "address_street": "Sampaguita St.",
                    "address_barangay": "",
                    "address_city": "",
                    "address_province": "",
                    "precinct": "101A",
                    "pwd": "",
                    "indigenous": "",
                    "solo_parent": "",
                    "voter_status": "on",
                    "status": "Alive",
                    "password1": "StrongPass123!",
                    "password2": "StrongPass123!",
                    "valid_id_image": SimpleUploadedFile(
                        "valid-id.gif",
                        TEST_GIF,
                        content_type="image/gif",
                    ),
                },
            )

        self.assertRedirects(response, reverse("portal_pending_verification"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            sorted(mail.outbox[0].to),
            ["secretary1@example.com", "secretary2@example.com"],
        )
        self.assertIn("Pending resident registration verification", mail.outbox[0].subject)
        self.assertIn("Juan Dela Cruz", mail.outbox[0].body)
        self.assertNotIn("Review queue:", mail.outbox[0].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
    )
    def test_secretary_approval_emails_resident(self):
        secretary_group, _ = Group.objects.get_or_create(name="Secretary")
        secretary = User.objects.create_user(
            username="approvalsecretary",
            password="StrongPass123!",
        )
        secretary.groups.add(secretary_group)

        resident_user = User.objects.create_user(
            username="approvedresident",
            email="approvedresident@example.com",
            password="StrongPass123!",
        )
        pending_profile = UserProfile.objects.create(
            user=resident_user,
            first_name="Juan",
            last_name="Dela Cruz",
            birth_date="2000-01-15",
            address="123 Sampaguita St., Purok 1",
            is_verified=False,
        )
        resident = Resident.objects.create(
            first_name="Juan",
            last_name="Dela Cruz",
            birth_date="2000-01-15",
            gender="Male",
            civil_status="Single",
        )

        self.client.login(username="approvalsecretary", password="StrongPass123!")
        response = self.client.post(
            reverse("review_pending_verification", args=[pending_profile.id]),
            data={
                "action": "approve",
                "resident_id": resident.id,
            },
        )

        self.assertRedirects(response, reverse("pending_verifications"))
        pending_profile.refresh_from_db()
        self.assertTrue(pending_profile.is_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["approvedresident@example.com"])
        self.assertIn("approved", mail.outbox[0].subject.lower())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
    )
    def test_secretary_rejection_emails_resident(self):
        secretary_group, _ = Group.objects.get_or_create(name="Secretary")
        secretary = User.objects.create_user(
            username="rejectsecretary",
            password="StrongPass123!",
        )
        secretary.groups.add(secretary_group)

        resident_user = User.objects.create_user(
            username="rejectedresident",
            email="rejectedresident@example.com",
            password="StrongPass123!",
        )
        pending_profile = UserProfile.objects.create(
            user=resident_user,
            first_name="Maria",
            last_name="Santos",
            birth_date="1999-05-10",
            address="Blk 2 Lot 5 Gulod",
            is_verified=False,
        )

        self.client.login(username="rejectsecretary", password="StrongPass123!")
        response = self.client.post(
            reverse("review_pending_verification", args=[pending_profile.id]),
            data={"action": "reject"},
        )

        self.assertRedirects(response, reverse("pending_verifications"))
        resident_user.refresh_from_db()
        self.assertFalse(resident_user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["rejectedresident@example.com"])
        self.assertIn("rejected", mail.outbox[0].subject.lower())

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ComplaintWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        resident_group, _ = Group.objects.get_or_create(name="Resident")
        secretary_group, _ = Group.objects.get_or_create(name="Secretary")

        cls.resident_user = User.objects.create_user(username="resident1", password="StrongPass123!")
        cls.resident_user.groups.add(resident_group)
        cls.secretary_user = User.objects.create_user(username="secretary1", password="StrongPass123!")
        cls.secretary_user.groups.add(secretary_group)

        cls.resident = Resident.objects.create(
            first_name="Maria",
            last_name="Santos",
            birth_date="1998-05-10",
            gender="Female",
            civil_status="Single",
        )
        cls.profile = UserProfile.objects.create(
            user=cls.resident_user,
            resident=cls.resident,
            first_name="Maria",
            last_name="Santos",
            birth_date="1998-05-10",
            address="Blk 2 Lot 5 Gulod",
            is_verified=True,
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_secretary_opening_submitted_complaint_moves_it_to_under_review(self):
        complaint = Complaint.objects.create(
            resident=self.resident,
            title="Noise Complaint",
            description="Loud noise late at night.",
            filed_by=self.resident_user,
        )

        self.client.login(username="secretary1", password="StrongPass123!")
        response = self.client.get(reverse("complaint_detail", args=[complaint.id]))

        self.assertEqual(response.status_code, 200)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "Under Review")

    def test_resident_can_withdraw_complaint(self):
        complaint = Complaint.objects.create(
            resident=self.resident,
            title="Boundary Dispute",
            description="A dispute about lot boundaries.",
            status="Under Review",
            filed_by=self.resident_user,
        )

        self.client.login(username="resident1", password="StrongPass123!")
        response = self.client.post(reverse("withdraw_complaint", args=[complaint.id]))

        self.assertRedirects(response, reverse("complaint_detail", args=[complaint.id]))
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "Withdrawn")

    def test_secretary_cannot_withdraw_complaint_through_status_update(self):
        complaint = Complaint.objects.create(
            resident=self.resident,
            title="Water Issue",
            description="Water drainage complaint.",
            status="Under Review",
            filed_by=self.resident_user,
        )

        self.client.login(username="secretary1", password="StrongPass123!")
        response = self.client.post(
            reverse("update_complaint_status", args=[complaint.id]),
            {"status": "Withdrawn"},
        )

        self.assertRedirects(response, reverse("complaint_detail", args=[complaint.id]))
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "Under Review")

    def test_complaint_form_rejects_whitespace_title_and_short_description(self):
        form = ComplaintForm(
            data={
                "resident": self.resident.id,
                "title": "   ",
                "description": "Too short",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)
        self.assertIn("description", form.errors)


class HouseholdValidationTests(TestCase):
    def test_household_form_rejects_whitespace_required_fields(self):
        form = HouseholdForm(data={"house_number": "   ", "street": "   "})

        self.assertFalse(form.is_valid())
        self.assertIn("house_number", form.errors)
        self.assertIn("street", form.errors)


class AdminLogoutTests(TestCase):
    def test_admin_header_logout_uses_main_logout_route(self):
        user = User.objects.create_superuser(
            username="adminlogout1",
            email="adminlogout1@example.com",
            password="StrongPass123!",
        )

        self.client.force_login(user)
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/logout/"')

    def test_logout_redirects_to_main_login_page(self):
        user = User.objects.create_superuser(
            username="adminlogout2",
            email="adminlogout2@example.com",
            password="StrongPass123!",
        )

        self.client.force_login(user)
        response = self.client.post(reverse("logout"), follow=True)

        self.assertRedirects(response, reverse("login"))


class AdminUserAddTests(TestCase):
    def test_admin_add_user_page_includes_email_field(self):
        user = User.objects.create_superuser(
            username="adminuseradd",
            email="adminuseradd@example.com",
            password="StrongPass123!",
        )

        self.client.force_login(user)
        response = self.client.get(reverse("admin:auth_user_add"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="email"')


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.com",
)
class ResidentPasswordResetTests(TestCase):
    def setUp(self):
        self.resident_group, _ = Group.objects.get_or_create(name="Resident")
        self.staff_group, _ = Group.objects.get_or_create(name="Staff")

    def test_password_reset_sends_email_for_resident_account(self):
        user = User.objects.create_user(
            username="resetresident",
            email="resetresident@example.com",
            password="OldStrongPass123!",
        )
        user.groups.add(self.resident_group)
        UserProfile.objects.create(
            user=user,
            first_name="Reset",
            last_name="Resident",
            birth_date="2000-01-15",
            address="Purok 1",
            is_verified=True,
        )

        response = self.client.post(
            reverse("password_reset"),
            {
                "username": "resetresident",
                "email": "resetresident@example.com",
            },
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["resetresident@example.com"])
        self.assertIn("password-reset-confirm", mail.outbox[0].body)

    def test_password_reset_does_not_email_when_username_and_email_do_not_match(self):
        user = User.objects.create_user(
            username="residentalpha",
            email="residentalpha@example.com",
            password="OldStrongPass123!",
        )
        user.groups.add(self.resident_group)
        UserProfile.objects.create(
            user=user,
            first_name="Resident",
            last_name="Alpha",
            birth_date="1997-03-15",
            address="Purok 4",
            is_verified=True,
        )

        response = self.client.post(
            reverse("password_reset"),
            {
                "username": "wrongusername",
                "email": "residentalpha@example.com",
            },
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_does_not_email_non_resident_accounts(self):
        user = User.objects.create_user(
            username="staffmember",
            email="staffmember@example.com",
            password="OldStrongPass123!",
        )
        user.groups.add(self.staff_group)
        UserProfile.objects.create(
            user=user,
            first_name="Staff",
            last_name="Member",
            birth_date="1999-01-01",
            address="Office",
            is_verified=True,
        )

        response = self.client.post(
            reverse("password_reset"),
            {
                "username": "staffmember",
                "email": "staffmember@example.com",
            },
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_confirm_updates_password(self):
        user = User.objects.create_user(
            username="changeme",
            email="changeme@example.com",
            password="OldStrongPass123!",
        )
        user.groups.add(self.resident_group)
        UserProfile.objects.create(
            user=user,
            first_name="Change",
            last_name="Me",
            birth_date="1998-05-10",
            address="Purok 2",
            is_verified=True,
        )

        response = self.client.post(
            reverse("password_reset"),
            {
                "username": "changeme",
                "email": "changeme@example.com",
            },
        )
        self.assertRedirects(response, reverse("password_reset_done"))
        reset_email = mail.outbox[0].body
        match = re.search(r"http://testserver(?P<path>/password-reset-confirm/[^\s]+/)", reset_email)
        self.assertIsNotNone(match)

        confirm_response = self.client.get(match.group("path"))
        self.assertEqual(confirm_response.status_code, 302)
        final_path = confirm_response["Location"]

        completion_response = self.client.post(
            final_path,
            {
                "new_password1": "NewStrongPass456!",
                "new_password2": "NewStrongPass456!",
            },
        )

        self.assertRedirects(completion_response, reverse("password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewStrongPass456!"))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.com",
)
class ServiceRequestNotificationTests(TestCase):
    def test_service_request_notification_creates_in_app_and_email_notifications(self):
        resident_user = User.objects.create_user(
            username="residentnotify",
            email="residentnotify@example.com",
            password="StrongPass123!",
        )
        resident = Resident.objects.create(
            first_name="Rina",
            last_name="Lopez",
            birth_date="1995-08-01",
            gender="Female",
            civil_status="Single",
        )
        profile = UserProfile.objects.create(
            user=resident_user,
            resident=resident,
            first_name="Rina",
            last_name="Lopez",
            birth_date="1995-08-01",
            address="Purok 3",
            is_verified=True,
        )
        service_type = ServiceType.objects.create(
            name="Barangay Clearance",
            fee=50,
            voter_fee=25,
            non_voter_fee=50,
        )
        service_request = ServiceRequest.objects.create(
            resident=resident,
            service_type=service_type,
            status="Under Review",
            created_by=resident_user,
        )

        notification = notify_resident_for_service_request(
            service_request,
            title="Request Under Review",
            message="Your Barangay Clearance request is now marked as Under Review.",
        )

        self.assertIsNotNone(notification)
        self.assertTrue(
            Notification.objects.filter(
                user=resident_user,
                category="service_request",
                target_url=f"/service-requests/{service_request.id}/",
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["residentnotify@example.com"])
        self.assertIn("Request Under Review", mail.outbox[0].subject)
        self.assertIn(service_request.document_number, mail.outbox[0].body)
        self.assertIn("Under Review", mail.outbox[0].body)

    def test_service_request_notification_skips_email_when_resident_has_no_email(self):
        resident_user = User.objects.create_user(
            username="residentnoemail",
            email="",
            password="StrongPass123!",
        )
        resident = Resident.objects.create(
            first_name="Marco",
            last_name="Diaz",
            birth_date="1993-04-12",
            gender="Male",
            civil_status="Single",
        )
        UserProfile.objects.create(
            user=resident_user,
            resident=resident,
            first_name="Marco",
            last_name="Diaz",
            birth_date="1993-04-12",
            address="Purok 5",
            is_verified=True,
        )
        service_type = ServiceType.objects.create(
            name="Certificate of Residency",
            fee=50,
            voter_fee=25,
            non_voter_fee=50,
        )
        service_request = ServiceRequest.objects.create(
            resident=resident,
            service_type=service_type,
            status="Processing",
            created_by=resident_user,
        )

        notification = notify_resident_for_service_request(
            service_request,
            title="Request Processing",
            message="Your Certificate of Residency request is now in processing.",
        )

        self.assertIsNotNone(notification)
        self.assertTrue(
            Notification.objects.filter(
                user=resident_user,
                category="service_request",
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 0)


class PortalServiceTypeSyncTests(TestCase):
    def test_portal_uses_named_service_types_when_available(self):
        named = ServiceType.objects.create(
            name="Barangay Clearance",
            fee=100,
            voter_fee=55,
            non_voter_fee=80,
        )
        ServiceType.objects.create(
            name="Service Request",
            fee=50,
            voter_fee=25,
            non_voter_fee=40,
        )

        services = get_portal_services()
        clearance = next(service for service in services if service["slug"] == "barangay-clearance")

        self.assertEqual(clearance["service_type"].id, named.id)
        self.assertEqual(clearance["voter_fee"], named.voter_fee)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.com",
)
class SecretarySubmissionEmailTests(TestCase):
    def setUp(self):
        self.secretary_group, _ = Group.objects.get_or_create(name="Secretary")

        self.secretary_one = User.objects.create_user(
            username="secretary_mail_1",
            email="secretary1@example.com",
            password="StrongPass123!",
        )
        self.secretary_one.groups.add(self.secretary_group)

        self.secretary_two = User.objects.create_user(
            username="secretary_mail_2",
            email="secretary2@example.com",
            password="StrongPass123!",
        )
        self.secretary_two.groups.add(self.secretary_group)

        self.secretary_without_email = User.objects.create_user(
            username="secretary_no_mail",
            email="",
            password="StrongPass123!",
        )
        self.secretary_without_email.groups.add(self.secretary_group)

    def test_service_request_submission_email_goes_to_all_secretaries(self):
        resident_user = User.objects.create_user(
            username="service_resident",
            email="resident@example.com",
            password="StrongPass123!",
        )
        resident = Resident.objects.create(
            first_name="Ana",
            last_name="Rivera",
            birth_date="1996-07-12",
            gender="Female",
            civil_status="Single",
        )
        service_type = ServiceType.objects.create(
            name="Barangay Clearance",
            fee=50,
            voter_fee=25,
            non_voter_fee=50,
        )
        service_request = ServiceRequest.objects.create(
            resident=resident,
            service_type=service_type,
            purpose="Local Employment",
            status="Submitted",
            created_by=resident_user,
        )

        notify_secretaries_of_service_request(service_request)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            sorted(mail.outbox[0].to),
            ["secretary1@example.com", "secretary2@example.com"],
        )
        self.assertIn("service request", mail.outbox[0].subject.lower())
        self.assertIn("Ana Rivera", mail.outbox[0].body)
        self.assertIn("Barangay Clearance", mail.outbox[0].body)

    def test_complaint_submission_email_goes_to_all_secretaries(self):
        resident_user = User.objects.create_user(
            username="complaint_resident",
            email="complaintresident@example.com",
            password="StrongPass123!",
        )
        resident = Resident.objects.create(
            first_name="Leo",
            last_name="Martinez",
            birth_date="1994-02-20",
            gender="Male",
            civil_status="Single",
        )
        complaint = Complaint.objects.create(
            resident=resident,
            title="Noise Complaint",
            description="Excessive videoke late at night.",
            filed_by=resident_user,
        )

        notify_secretaries_of_complaint(complaint)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            sorted(mail.outbox[0].to),
            ["secretary1@example.com", "secretary2@example.com"],
        )
        self.assertIn("complaint", mail.outbox[0].subject.lower())
        self.assertIn("Leo Martinez", mail.outbox[0].body)
        self.assertIn("Noise Complaint", mail.outbox[0].body)
