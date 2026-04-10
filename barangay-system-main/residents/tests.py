import shutil
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Complaint, Resident, UserProfile


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
                "last_name": "Dela Cruz",
                "birthdate": "2000-01-15",
                "address": "123 Sampaguita St., Purok 1",
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
        self.assertEqual(profile.address, "123 Sampaguita St., Purok 1")
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
                "last_name": "Live",
                "birthdate": "2001-03-21",
                "address": "Purok 2, Gulod",
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
