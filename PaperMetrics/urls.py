"""PaperMetrics URL Configuration

This module defines the URL routing for the entire Django project. It's a gateway to all other URL configurations in the application's apps.

For more information on URL configuration:
https://docs.djangoproject.com/en/3.0/topics/http/urls/
"""

from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path

from . import health

# Admin URL patterns
urlpatterns = [
    path("healthz/", health.liveness, name="healthz"),
    path("readyz/", health.readiness, name="readyz"),
    path(f"{settings.ADMIN_PATH}/", admin.site.urls),
]

# Application specific URL patterns with internationalization support
urlpatterns += i18n_patterns(
    # Include the API app URLs
    path("api/", include("api.urls")),

    # Include the frontend app URLs
    path("", include("frontend.urls")),

    # Include the authorization app URLs for authentication related paths
    path("auth/", include("authorization.urls")),

    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
