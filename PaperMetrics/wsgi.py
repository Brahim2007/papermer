"""
WSGI config for PaperMetrics project.

This module contains the WSGI application used by Django's development server
and any production WSGI deployments. It should expose a module-level variable
named `application`. Django's `runserver` and `wsgi` modules use this application.

For more information on this file, see
https://docs.djangoproject.com/en/3.0/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

# Point to the settings module defined in the Django project.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PaperMetrics.settings')

# This application object is used by any WSGI server configured to use this file.
application = get_wsgi_application()
