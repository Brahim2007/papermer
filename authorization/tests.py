from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from PaperMetrics.middleware import AuthRateLimitMiddleware
from .forms import LoginForm, SignupForm
from .views import logout_


class LoginFormTests(SimpleTestCase):
    def test_invalid_email_is_rejected_without_database_lookup(self):
        form = LoginForm({"email": "not-an-email", "password": "secret"})
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_remember_me_is_optional_and_defaults_to_false_when_unchecked(self):
        form = LoginForm({"email": "reader@example.org", "password": "secret"})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.cleaned_data["remember_me"])

    def test_auth_fields_expose_password_manager_autocomplete_hints(self):
        login_form = LoginForm()
        signup_form = SignupForm()
        self.assertEqual(
            login_form.fields["password"].widget.attrs["autocomplete"],
            "current-password",
        )
        self.assertEqual(
            signup_form.fields["password1"].widget.attrs["autocomplete"],
            "new-password",
        )


class AuthenticationRouteTests(SimpleTestCase):
    def test_password_recovery_routes_are_available(self):
        for name in (
            "password_reset",
            "password_reset_done",
            "password_reset_complete",
        ):
            self.assertIsNotNone(resolve(reverse(name)).func)

    def test_logout_rejects_get_requests(self):
        request = RequestFactory().get("/auth/logout/")
        response = logout_(request)
        self.assertEqual(response.status_code, 405)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "auth-rate-limit-tests",
        }
    }
)
class AuthRateLimitTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = AuthRateLimitMiddleware(lambda request: HttpResponse("ok"))

    def test_login_post_is_limited_after_ten_attempts(self):
        for _ in range(10):
            response = self.middleware(
                self.factory.post("/auth/login/", REMOTE_ADDR="192.0.2.10")
            )
            self.assertEqual(response.status_code, 200)

        response = self.middleware(
            self.factory.post("/auth/login/", REMOTE_ADDR="192.0.2.10")
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "300")

    def test_non_post_request_is_not_limited(self):
        for _ in range(15):
            response = self.middleware(
                self.factory.get("/auth/login/", REMOTE_ADDR="192.0.2.11")
            )
        self.assertEqual(response.status_code, 200)

    def test_localized_login_path_uses_the_same_limit(self):
        for _ in range(5):
            response = self.middleware(
                self.factory.post("/auth/login/", REMOTE_ADDR="192.0.2.12")
            )
            self.assertEqual(response.status_code, 200)
        for _ in range(5):
            response = self.middleware(
                self.factory.post("/ar/auth/login/", REMOTE_ADDR="192.0.2.12")
            )
            self.assertEqual(response.status_code, 200)

        response = self.middleware(
            self.factory.post("/ar/auth/login/", REMOTE_ADDR="192.0.2.12")
        )
        self.assertEqual(response.status_code, 429)
