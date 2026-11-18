import os
from pathlib import Path

from config.database import database_config

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ.get('PROGRAM_SECRET_KEY', 'development-only-change-this-key')
DEBUG = os.environ.get('PROGRAM_DEBUG', '1') == '1'
ALLOWED_HOSTS = os.environ.get('PROGRAM_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'program']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.debug', 'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': database_config(BASE_DIR)}
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'ja'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'media'
PROCEEDINGS_ROOT = Path(os.environ.get('PROCEEDINGS_ROOT', str(MEDIA_ROOT)))
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/organize/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
VIVLIOSTYLE_CLI = os.environ.get('VIVLIOSTYLE_CLI', 'vivliostyle')
PROGRAM_PDF_TIMEOUT = int(os.environ.get('PROGRAM_PDF_TIMEOUT', '300'))

# Development prints reset emails to the terminal; production uses SMTP.
EMAIL_BACKEND = os.environ.get('PROGRAM_EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('PROGRAM_EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('PROGRAM_EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('PROGRAM_EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('PROGRAM_EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('PROGRAM_EMAIL_USE_TLS', '1') == '1'
EMAIL_USE_SSL = os.environ.get('PROGRAM_EMAIL_USE_SSL', '0') == '1'
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get('PROGRAM_DEFAULT_FROM_EMAIL', 'webmaster@localhost')
PASSWORD_RESET_TIMEOUT = 60 * 60

# Optional Times New Roman files: times.ttf, timesi.ttf, timesbd.ttf.
PROCEEDINGS_FONT_DIR = Path(os.environ.get('PROCEEDINGS_FONT_DIR', str(BASE_DIR / 'ttfonts' / 'TimesNewRomanPSMT')))

# Processed public PDFs; keep separate from submitted originals.
PROCEEDINGS_PUBLISH_ROOT = Path(os.environ.get('PROCEEDINGS_PUBLISH_ROOT', str(BASE_DIR / 'published_proceedings')))
