import os
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .database import database_config


class DatabaseConfigTests(SimpleTestCase):
    def config(self, **env):
        with patch.dict(os.environ, env, clear=True):
            return database_config(Path('/app'))

    def test_default_sqlite(self):
        self.assertEqual(self.config()['NAME'], '/app/db.sqlite3')
        self.assertEqual(self.config()['ENGINE'], 'django.db.backends.sqlite3')

    def test_sqlite_persistent_path(self):
        self.assertEqual(self.config(PROGRAM_DB_NAME='/data/db.sqlite3')['NAME'], '/data/db.sqlite3')

    def test_postgresql_credentials_and_tls(self):
        db = self.config(PROGRAM_DB_ENGINE='postgresql', PROGRAM_DB_NAME='program',
                         PROGRAM_DB_USER='editor', PROGRAM_DB_PASSWORD='a:@/# password',
                         PROGRAM_DB_HOST='database', PROGRAM_DB_PORT='5433',
                         PROGRAM_DB_SSLMODE='verify-full', PROGRAM_DB_SSLROOTCERT='/data/ca.pem')
        self.assertEqual(db['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(db['PASSWORD'], 'a:@/# password')
        self.assertEqual(db['HOST'], 'database')
        self.assertEqual(db['PORT'], '5433')
        self.assertEqual(db['OPTIONS']['sslmode'], 'verify-full')
        self.assertEqual(db['OPTIONS']['sslrootcert'], '/data/ca.pem')
        self.assertTrue(db['CONN_HEALTH_CHECKS'])

    def test_postgresql_socket_and_peer_auth(self):
        db = self.config(PROGRAM_DB_ENGINE='postgresql', PROGRAM_DB_NAME='program',
                         PROGRAM_DB_USER='editor', PROGRAM_DB_HOST='')
        self.assertEqual(db['HOST'], '')
        self.assertEqual(db['PASSWORD'], '')
        self.assertNotIn('sslmode', db['OPTIONS'])

    def test_invalid_configuration_never_falls_back_to_sqlite(self):
        for env in [dict(PROGRAM_DB_ENGINE='postgres'),
                    dict(PROGRAM_DB_ENGINE='postgresql'),
                    dict(PROGRAM_DB_ENGINE='postgresql', PROGRAM_DB_NAME='program'),
                    dict(PROGRAM_DB_ENGINE='postgresql', PROGRAM_DB_USER='editor')]:
            with self.subTest(env=env), self.assertRaises(ImproperlyConfigured):
                self.config(**env)
