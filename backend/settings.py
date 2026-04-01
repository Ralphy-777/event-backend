import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name: str, default: str = '') -> list[str]:
    value = os.environ.get(name, default)
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(',') if item.strip()]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def with_extra_hosts(*hosts: str) -> list[str]:
    items: list[str] = []
    for host in hosts:
        if host and host not in items:
            items.append(host)
    return items

SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-insecure-key-change-in-production')
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

# Allow Render domain + any custom domain automatically
ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'event-backend-5-v9tx.onrender.com',
    '.onrender.com',
    '.vercel.app',
    os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip(),
]
ALLOWED_HOSTS = [h for h in ALLOWED_HOSTS if h]  # remove empty strings

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    'jazzmin',
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'user',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'channels',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

_extra_csrf = env_list('CSRF_TRUSTED_ORIGINS')
CSRF_TRUSTED_ORIGINS = list({
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'https://event-bookings-eosin.vercel.app',
    'https://event-booking-chi.vercel.app',
    'https://event-bookings-git-main-ralphy-777s-projects.vercel.app',
    'https://event-backend-5-v9tx.onrender.com',
    'https://*.vercel.app',
    *_extra_csrf,
})

ROOT_URLCONF = 'backend.urls'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user': '200/minute',
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'AUTH_HEADER_TYPES': ('Bearer',),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
}

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'
ASGI_APPLICATION = 'backend.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# Database — uses DATABASE_URL on Render, falls back to local PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'eventpro'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }

AUTH_USER_MODEL = 'user.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security headers (production only)
# X_FRAME_OPTIONS must be SAMEORIGIN (not DENY) so the Django admin iframes work
X_FRAME_OPTIONS = 'SAMEORIGIN'
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 0  # keep 0 — Render handles HTTPS termination
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False

# GCash Manual Payment
GCASH_RECEIVER_NUMBER = os.environ.get('GCASH_RECEIVER_NUMBER', '09939261681')
GCASH_RECEIVER_NAME = os.environ.get('GCASH_RECEIVER_NAME', 'Liberato Villarojo')

# PayMongo
PAYMONGO_SECRET_KEY = os.environ.get('PAYMONGO_SECRET_KEY', '')
PAYMONGO_PUBLIC_KEY = os.environ.get('PAYMONGO_PUBLIC_KEY', '')
PAYMONGO_BASE_URL = 'https://api.paymongo.com/v1'

# Frontend URL
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://event-bookings-eosin.vercel.app')

# Cache — Redis on Render if available, otherwise local memory
_REDIS_URL = os.environ.get('REDIS_URL', '')
if _REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = f'EventPro <{os.environ.get("EMAIL_HOST_USER", "")}>'

# Jazzmin Admin UI
JAZZMIN_SETTINGS = {
    # ── Branding ──────────────────────────────────────────────────────────────
    'site_title': 'EventPro Admin',
    'site_header': 'EventPro',
    'site_brand': 'EventPro',
    'site_logo': None,
    'site_logo_classes': None,
    'site_icon': None,
    'welcome_sign': 'Welcome to EventPro Admin Panel',
    'copyright': 'EventPro © 2025',

    # ── Search ────────────────────────────────────────────────────────────────
    'search_model': ['user.User', 'user.Booking'],

    # ── User avatar ───────────────────────────────────────────────────────────
    'user_avatar': None,

    # ── Top menu ──────────────────────────────────────────────────────────────
    'topmenu_links': [
        {'name': 'Dashboard', 'url': 'admin:index', 'permissions': ['auth.view_user']},
        {'name': 'View Site', 'url': 'https://event-bookings-git-main-ralphy-777s-projects.vercel.app', 'new_window': True},
        {'model': 'user.User'},
        {'model': 'user.Booking'},
    ],

    # ── User menu ─────────────────────────────────────────────────────────────
    'usermenu_links': [
        {'name': 'View Site', 'url': 'https://event-bookings-git-main-ralphy-777s-projects.vercel.app', 'new_window': True, 'icon': 'fas fa-external-link-alt'},
    ],

    # ── Sidebar ───────────────────────────────────────────────────────────────
    'show_sidebar': True,
    'navigation_expanded': True,
    'hide_apps': [],
    'hide_models': [],
    'order_with_respect_to': [
        'user',
        'user.User',
        'user.Booking',
        'user.Payment',
        'user.EventType',
        'user.Review',
        'user.ReviewReply',
        'user.Notification',
        'user.ContactMessage',
        'user.Video',
    ],

    # ── Custom links in sidebar ───────────────────────────────────────────────
    'custom_links': {
        'user': [{
            'name': 'View Frontend',
            'url': 'https://event-bookings-git-main-ralphy-777s-projects.vercel.app',
            'icon': 'fas fa-globe',
            'new_window': True,
        }],
    },

    # ── Icons ─────────────────────────────────────────────────────────────────
    'icons': {
        'auth': 'fas fa-users-cog',
        'auth.group': 'fas fa-users',
        'user.user': 'fas fa-user-circle',
        'user.booking': 'fas fa-calendar-check',
        'user.payment': 'fas fa-credit-card',
        'user.eventtype': 'fas fa-tags',
        'user.review': 'fas fa-star',
        'user.reviewreply': 'fas fa-reply',
        'user.notification': 'fas fa-bell',
        'user.contactmessage': 'fas fa-envelope-open-text',
        'user.video': 'fas fa-video',
    },
    'default_icon_parents': 'fas fa-folder',
    'default_icon_children': 'fas fa-circle',

    # ── Related modals ────────────────────────────────────────────────────────
    'related_modal_active': True,

    # ── Custom CSS/JS — set to None to avoid 404s breaking the UI ────────────
    'custom_css': None,
    'custom_js': None,

    # ── Fonts ─────────────────────────────────────────────────────────────────
    'use_google_fonts_cdn': True,

    # ── UI Builder (disable in production) ───────────────────────────────────
    'show_ui_builder': False,

    # ── Change form layout ────────────────────────────────────────────────────
    'changeform_format': 'horizontal_tabs',
    'changeform_format_overrides': {
        'user.user': 'collapsible',
        'user.booking': 'vertical_tabs',
    },

    # ── Language chooser ──────────────────────────────────────────────────────
    'language_chooser': False,
}

JAZZMIN_UI_TWEAKS = {
    'navbar_small_text': False,
    'footer_small_text': False,
    'body_small_text': False,
    'brand_small_text': False,
    'brand_colour': 'navbar-primary',
    'accent': 'accent-primary',
    'navbar': 'navbar-dark',
    'no_navbar_border': False,
    'navbar_fixed': True,
    'layout_boxed': False,
    'footer_fixed': False,
    'sidebar_fixed': True,
    'sidebar': 'sidebar-dark-primary',
    'sidebar_nav_small_text': False,
    'sidebar_disable_expand': False,
    'sidebar_nav_child_indent': True,
    'sidebar_nav_compact_style': False,
    'sidebar_nav_legacy_style': False,
    'sidebar_nav_flat_style': False,
    'theme': 'default',
    'dark_mode_theme': None,
    'button_classes': {
        'primary': 'btn-primary',
        'secondary': 'btn-secondary',
        'info': 'btn-info',
        'warning': 'btn-warning',
        'danger': 'btn-danger',
        'success': 'btn-success',
    },
    'actions_sticky_top': True,
}
