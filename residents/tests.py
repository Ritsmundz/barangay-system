from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["testserver", "127.0.0.1", "localhost"])
class LogoutViewTests(TestCase):
    def test_logout_redirects_to_login(self):
        user = User.objects.create_user(username="logoutcase", password="StrongPass123!")
        self.client.login(username="logoutcase", password="StrongPass123!")

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
