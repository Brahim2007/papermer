"""Django settings for PaperMetrix.

All deployment-specific values are read from environment variables.  The
defaults below are suitable for local development only and intentionally do
not contain real credentials.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
APP_VERSION = os.getenv("APP_VERSION", "development")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_optional_float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else None


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-key-change-me")
if not DEBUG and SECRET_KEY == "unsafe-development-key-change-me":
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "api",
    "frontend",
    "authorization",
    "crispy_forms",
    "crispy_bootstrap4",
    "django_celery_beat",
    "rest_framework",
    "rest_framework.authtoken",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "PaperMetrics.middleware.AuthRateLimitMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "PaperMetrics.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

WSGI_APPLICATION = "PaperMetrics.wsgi.application"
ASGI_APPLICATION = "PaperMetrics.asgi.application"

def database_config() -> dict:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return {
            "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
            "NAME": os.getenv("DB_NAME", "paper"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
        }

    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use postgres or postgresql.")
    if not parsed.hostname or not parsed.path.lstrip("/"):
        raise ImproperlyConfigured("DATABASE_URL must include a host and database.")
    supported_options = {
        "channel_binding",
        "sslcert",
        "sslkey",
        "sslmode",
        "sslrootcert",
    }
    options = {
        key: value
        for key, value in parse_qsl(parsed.query)
        if key in supported_options
    }
    return {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
    }


DATABASES = {"default": database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "en")
LANGUAGES = [
    ("en", "English"),
    ("ar", "العربية"),
    ("tr", "Türkçe"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
AUTH_USER_MODEL = "authorization.User"
ADMIN_PATH = os.getenv("DJANGO_ADMIN_PATH", "admin").strip("/")
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap4"
CRISPY_TEMPLATE_PACK = "bootstrap4"

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@localhost")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_PREFETCH_MULTIPLIER = int(
    os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1")
)

CACHE_URL = os.getenv("DJANGO_CACHE_URL", "").strip()
CACHES = (
    {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
        }
    }
    if CACHE_URL
    else {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "papermetrix-development",
        }
    }
)

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
}

MENDELEY_ID = os.getenv("MENDELEY_ID", "")
MENDELEY_SECRET = os.getenv("MENDELEY_SECRET", "")
TWITTER_BEARER = os.getenv("TWITTER_BEARER", "")
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "")
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS = float(
    os.getenv("SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS", "1.1")
)
CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL", "")
ARXIV_MIN_INTERVAL_SECONDS = float(os.getenv("ARXIV_MIN_INTERVAL_SECONDS", "3.0"))
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", CROSSREF_EMAIL)
UNPAYWALL_MIN_INTERVAL_SECONDS = float(
    os.getenv("UNPAYWALL_MIN_INTERVAL_SECONDS", "0.2")
)

# Live retrieval remains reproducible: the dense component uses a versioned
# SPECTER2 cache and reports when it falls back to sparse hybrid retrieval.
SEMANTIC_SEARCH_ENABLED = env_bool("SEMANTIC_SEARCH_ENABLED", True)
SPECTER2_CACHE_PATH = os.getenv(
    "SPECTER2_CACHE_PATH",
    "artifacts/paper_recommendation_scope_v2.specter2.npz",
)
LIVE_SEARCH_CACHE_SECONDS = int(os.getenv("LIVE_SEARCH_CACHE_SECONDS", "300"))

# Online evaluation stores keyed query digests by default. Raw query retention is
# a separate, explicit opt-in because scholarly queries may reveal research intent.
RETRIEVAL_TELEMETRY_ENABLED = env_bool("RETRIEVAL_TELEMETRY_ENABLED", True)
RETRIEVAL_TELEMETRY_STORE_QUERY_TEXT = env_bool(
    "RETRIEVAL_TELEMETRY_STORE_QUERY_TEXT", False
)
RETRIEVAL_TELEMETRY_HMAC_KEY = os.getenv(
    "RETRIEVAL_TELEMETRY_HMAC_KEY", SECRET_KEY
)

# LLM query expansion is an isolated experimental arm. Enabling it authorizes
# transmission of selected queries to the configured provider.
LLM_QUERY_EXPANSION_ENABLED = env_bool("LLM_QUERY_EXPANSION_ENABLED", False)
LLM_QUERY_EXPANSION_TRAFFIC_PERCENT = min(
    max(int(os.getenv("LLM_QUERY_EXPANSION_TRAFFIC_PERCENT", "0")), 0), 100
)
LLM_QUERY_EXPANSION_ENDPOINT = os.getenv("LLM_QUERY_EXPANSION_ENDPOINT", "")
LLM_QUERY_EXPANSION_API_KEY = os.getenv("LLM_QUERY_EXPANSION_API_KEY", "")
LLM_QUERY_EXPANSION_MODEL = os.getenv("LLM_QUERY_EXPANSION_MODEL", "")
LLM_QUERY_EXPANSION_TIMEOUT_SECONDS = float(
    os.getenv("LLM_QUERY_EXPANSION_TIMEOUT_SECONDS", "8")
)
LLM_QUERY_EXPANSION_MAX_CHARS = int(
    os.getenv("LLM_QUERY_EXPANSION_MAX_CHARS", "1000")
)
LLM_QUERY_EXPANSION_MAX_OUTPUT_TOKENS = int(
    os.getenv("LLM_QUERY_EXPANSION_MAX_OUTPUT_TOKENS", "120")
)
LLM_QUERY_EXPANSION_CACHE_SECONDS = int(
    os.getenv("LLM_QUERY_EXPANSION_CACHE_SECONDS", "604800")
)
# Pricing is explicit experiment metadata rather than a hard-coded, time-sensitive
# assumption. Set these values from the provider price sheet used for each run.
LLM_QUERY_EXPANSION_INPUT_USD_PER_MILLION = env_optional_float(
    "LLM_QUERY_EXPANSION_INPUT_USD_PER_MILLION"
)
LLM_QUERY_EXPANSION_CACHED_INPUT_USD_PER_MILLION = env_optional_float(
    "LLM_QUERY_EXPANSION_CACHED_INPUT_USD_PER_MILLION"
)
LLM_QUERY_EXPANSION_OUTPUT_USD_PER_MILLION = env_optional_float(
    "LLM_QUERY_EXPANSION_OUTPUT_USD_PER_MILLION"
)
LLM_QUERY_EXPANSION_STAFF_ONLY = env_bool(
    "LLM_QUERY_EXPANSION_STAFF_ONLY", True
)
LLM_QUERY_EXPANSION_DAILY_BUDGET_USD = float(
    os.getenv("LLM_QUERY_EXPANSION_DAILY_BUDGET_USD", "1.0")
)
LLM_QUERY_EXPANSION_FAILURE_THRESHOLD = int(
    os.getenv("LLM_QUERY_EXPANSION_FAILURE_THRESHOLD", "3")
)
LLM_QUERY_EXPANSION_FAILURE_WINDOW_SECONDS = int(
    os.getenv("LLM_QUERY_EXPANSION_FAILURE_WINDOW_SECONDS", "300")
)
LLM_QUERY_EXPANSION_CIRCUIT_COOLDOWN_SECONDS = int(
    os.getenv("LLM_QUERY_EXPANSION_CIRCUIT_COOLDOWN_SECONDS", "300")
)

SEMANTIC_SEARCH_WARMUP_QUERY = os.getenv(
    "SEMANTIC_SEARCH_WARMUP_QUERY", ""
).strip()
SEMANTIC_SEARCH_REQUIRE_WARM_READY = env_bool(
    "SEMANTIC_SEARCH_REQUIRE_WARM_READY", False
)
SEMANTIC_SEARCH_WARMUP_RUNSERVER = env_bool(
    "SEMANTIC_SEARCH_WARMUP_RUNSERVER", False
)

# Topic taxonomy is deliberately configuration, not a hard-coded global secret.
SUBDISCIPLINES = {
    "Computer Science": [
        "Artificial Intelligence",
        "Information Retrieval",
        "Machine Learning",
        "Natural Language Processing",
    ],
    "Library and Information Science": [
        "Bibliometrics",
        "Digital Libraries",
        "Scholarly Communication",
    ],
}

SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "1209600"))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
TRUST_PROXY_HEADERS = env_bool("DJANGO_TRUST_PROXY_HEADERS", False)

if not DEBUG:
    if TRUST_PROXY_HEADERS:
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        USE_X_FORWARDED_HOST = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    # Container and reverse-proxy health probes use the private HTTP network.
    # Caddy still redirects public port 80 to HTTPS before proxying.
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$", r"^readyz/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)

LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}
