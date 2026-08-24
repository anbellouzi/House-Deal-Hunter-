"""
Auction Intelligence Platform - Django Settings

Works in two modes:
  LOCAL    - reads DB_NAME/DB_USER/... from .env
  RAILWAY  - reads DATABASE_URL / REDIS_URL injected by Railway service refs
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# -- Core ---------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-in-production")
DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "yes")

# Railway injects the public domain here. Keep localhost for dev.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".railway.app"]
_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if _railway_domain:
    ALLOWED_HOSTS.append(_railway_domain)
_extra_hosts = os.environ.get("ALLOWED_HOSTS", "")
if _extra_hosts:
    ALLOWED_HOSTS += [h.strip() for h in _extra_hosts.split(",") if h.strip()]

# Django 4+ requires the scheme for CSRF trusted origins.
CSRF_TRUSTED_ORIGINS = ["https://*.railway.app"]
if _railway_domain:
    CSRF_TRUSTED_ORIGINS.append("https://" + _railway_domain)

# -- Applications -------------------------------------------------------------
# Celery is optional. Without a Redis broker the app runs in "inline" mode:
# crawls and analysis execute synchronously when triggered from the admin.
# Set USE_CELERY=True only if you have a broker (Redis/Upstash) available.
USE_CELERY = os.environ.get("USE_CELERY", "False").lower() in ("true", "1", "yes")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "django_filters",
    # Local
    "apps.auctions",
    "apps.sources",
    "apps.analysis",
    "apps.alerts",
    "apps.dashboard",
]

if USE_CELERY:
    INSTALLED_APPS.insert(-5, "django_celery_beat")
    INSTALLED_APPS.insert(-5, "django_celery_results")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise must sit directly after SecurityMiddleware to serve static files.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "auction_intel.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "auction_intel.wsgi.application"

# -- Database -----------------------------------------------------------------
# Railway sets DATABASE_URL when you add Postgres and reference it.
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=not DEBUG,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "auction_intel"),
            "USER": os.environ.get("DB_USER", "postgres"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

# -- Static files (WhiteNoise) ------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -- Security (production only) -----------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# -- REST Framework -----------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

# -- Celery (only when USE_CELERY=True) ---------------------------------------
if USE_CELERY:
    CELERY_BROKER_URL = (
        os.environ.get("CELERY_BROKER_URL")
        or os.environ.get("REDIS_URL")
        or "redis://localhost:6379/0"
    )
    CELERY_RESULT_BACKEND = "django-db"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_TIMEZONE = TIME_ZONE
    CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
    CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

    # Managed Redis over TLS (rediss://) needs an explicit cert policy.
    if CELERY_BROKER_URL.startswith("rediss://"):
        import ssl
        CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE}
        CELERY_REDIS_BACKEND_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE}

# -- Crawler policy -----------------------------------------------------------
CRAWLER = {
    "CRAWL_DELAY_SECONDS": int(os.environ.get("CRAWL_DELAY_SECONDS", 5)),
    "MAX_RETRIES": int(os.environ.get("CRAWL_MAX_RETRIES", 3)),
    "REQUEST_TIMEOUT": int(os.environ.get("CRAWL_TIMEOUT", 30)),
    "USER_AGENT": os.environ.get(
        "CRAWLER_USER_AGENT",
        "AuctionIntelBot/1.0 (Pennsylvania Real Estate Research; "
        "contact: your@email.com)",
    ),
    "MIN_HISTORICAL_SAMPLE": int(os.environ.get("MIN_HISTORICAL_SAMPLE", 30)),
    "RESPECT_ROBOTS_TXT": True,   # never disable
}

# -- Bid4Assets public PA county pages ----------------------------------------
BID4ASSETS_PA_COUNTIES = {
    "delaware": "https://www.bid4assets.com/delawarecountysheriff",
    "montgomery": "https://www.bid4assets.com/montgomery",
    "philadelphia_foreclosure": "https://www.bid4assets.com/philaforeclosures",
    "philadelphia_tax": "https://www.bid4assets.com/philataxsales",
}

# -- Analysis thresholds ------------------------------------------------------
ANALYSIS = {
    "LOW_COMPETITION_MIN_BID_RATIO": float(
        os.environ.get("LOW_COMPETITION_MIN_BID_RATIO", 0.40)
    ),
    "LOW_COMPETITION_SCORE_THRESHOLD": int(
        os.environ.get("LOW_COMPETITION_SCORE_THRESHOLD", 70)
    ),
    "MAX_RISK_SCORE": int(os.environ.get("MAX_RISK_SCORE", 60)),
    "DEAL_SCORE_WEIGHTS": {
        "discount_to_market": 0.25,
        "rental_economics": 0.20,
        "low_competition": 0.15,
        "flip_economics": 0.15,
        "property_quality": 0.10,
        "neighborhood": 0.05,
        "resale_potential": 0.05,
        "risk_adjustment": 0.05,
    },
}

# -- Logging ------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps": {
            "handlers": ["console"],
            "level": os.environ.get("LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
