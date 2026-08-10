"""Minimal Django bootstrap so tests also run before pytest-django is installed."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")

import django

django.setup()
