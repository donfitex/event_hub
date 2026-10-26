from .base import *  # noqa

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
SECRET_KEY = SECRET_KEY or "test-secret-key-not-for-production"

# Faster tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

SITE_URL = "http://testserver"

REGISTRATION_CANCELLATION_CUTOFF_HOURS = 0