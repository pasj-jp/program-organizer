"""Import settings in fresh processes so environment and module caches cannot leak."""
import json
import os
from pathlib import Path
import subprocess
import sys

from django.test import SimpleTestCase


class SettingsTests(SimpleTestCase):
    def load(self, module='config.settings.production', **overrides):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('DJANGO_', 'PROCEEDINGS_'))}
        env.update(DJANGO_SECRET_KEY='test-only-secret-abcdefghijklmnopqrstuvwxyz-0123456789',
                   DJANGO_ALLOWED_HOSTS=' program.example.com, ,www.example.com ',
                   DJANGO_DB_NAME='program', DJANGO_DB_USER='program')
        env.update(overrides)
        code = '''import importlib, json, sys
s = importlib.import_module(sys.argv[1])
names = ['BASE_DIR', 'DEBUG', 'DATABASES', 'ALLOWED_HOSTS', 'EMAIL_BACKEND',
         'SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE',
         'SECURE_PROXY_SSL_HEADER', 'MEDIA_ROOT', 'PROCEEDINGS_ROOT']
print(json.dumps({name: getattr(s, name, None) for name in names}, default=str))
'''
        return subprocess.run([sys.executable, '-c', code, module], env=env,
                              capture_output=True, text=True, timeout=15)

    def test_production_defaults_and_paths(self):
        result = self.load(DJANGO_DEBUG='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertFalse(settings['DEBUG'])
        self.assertEqual(settings['BASE_DIR'], str(Path(__file__).resolve().parent.parent))
        self.assertEqual(settings['DATABASES']['default']['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(settings['ALLOWED_HOSTS'], ['program.example.com', 'www.example.com'])
        self.assertEqual(settings['EMAIL_BACKEND'], 'django.core.mail.backends.smtp.EmailBackend')
        for name in ['SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE']:
            self.assertTrue(settings[name])
        self.assertIsNone(settings['SECURE_PROXY_SSL_HEADER'])

    def test_missing_or_unsafe_required_settings(self):
        for env in [dict(DJANGO_SECRET_KEY=''), dict(DJANGO_SECRET_KEY='development-only-change-this-key'),
                    dict(DJANGO_ALLOWED_HOSTS=''), dict(DJANGO_ALLOWED_HOSTS='*'),
                    dict(DJANGO_DB_NAME=''), dict(DJANGO_DB_USER='')]:
            with self.subTest(env=env):
                result = self.load(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('ImproperlyConfigured', result.stderr)

    def test_proxy_and_persistent_media(self):
        result = self.load(DJANGO_TRUST_PROXY_SSL_HEADER='1', DJANGO_MEDIA_ROOT='/data/media')
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertEqual(settings['SECURE_PROXY_SSL_HEADER'], ['HTTP_X_FORWARDED_PROTO', 'https'])
        self.assertEqual(settings['MEDIA_ROOT'], '/data/media')
        self.assertEqual(settings['PROCEEDINGS_ROOT'], '/data/media')

    def test_development_aliases_keep_sqlite_and_project_root(self):
        for module in ['config.settings', 'config.settings.development']:
            with self.subTest(module=module):
                result = self.load(module)
                self.assertEqual(result.returncode, 0, result.stderr)
                settings = json.loads(result.stdout)
                self.assertTrue(settings['DEBUG'])
                self.assertEqual(settings['DATABASES']['default']['ENGINE'], 'django.db.backends.sqlite3')
                self.assertEqual(settings['BASE_DIR'], str(Path(__file__).resolve().parent.parent))

    def test_explicit_sqlite_for_migration(self):
        result = self.load(DJANGO_DB_ENGINE='sqlite', DJANGO_DB_NAME='/data/db.sqlite3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['DATABASES']['default']['NAME'], '/data/db.sqlite3')
