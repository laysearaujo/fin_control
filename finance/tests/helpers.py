from django.contrib.auth.models import User
from django.test import TestCase, Client


class AuthenticatedTestCase(TestCase):
    """Every owned model now requires an owner, and every view requires a logged-in
    user (LoginRequiredMiddleware) - this gives every test a ready-to-use user and
    an already-logged-in client, so existing tests only need to add owner=self.user
    to their .create() calls."""

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='pw')
        self.client = Client()
        self.client.force_login(self.user)
