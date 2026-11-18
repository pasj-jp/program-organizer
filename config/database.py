"""Database settings shared by development and production deployments."""
import os

from django.core.exceptions import ImproperlyConfigured


def database_config(base_dir, default_engine="sqlite"):
    engine = os.environ.get('PROGRAM_DB_ENGINE', default_engine)
    if engine == 'sqlite':
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get('PROGRAM_DB_NAME', str(base_dir / 'db.sqlite3')),
            'OPTIONS': {'timeout': 30},
        }
    if engine != 'postgresql':
        raise ImproperlyConfigured('PROGRAM_DB_ENGINE must be sqlite or postgresql.')
    if not os.environ.get('PROGRAM_DB_NAME') or not os.environ.get('PROGRAM_DB_USER'):
        raise ImproperlyConfigured('PostgreSQL requires PROGRAM_DB_NAME and PROGRAM_DB_USER.')
    options = {'connect_timeout': 10}
    for env_name, option in [('PROGRAM_DB_SSLMODE', 'sslmode'),
                             ('PROGRAM_DB_SSLROOTCERT', 'sslrootcert')]:
        if os.environ.get(env_name):
            options[option] = os.environ[env_name]
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['PROGRAM_DB_NAME'],
        'USER': os.environ['PROGRAM_DB_USER'],
        'PASSWORD': os.environ.get('PROGRAM_DB_PASSWORD', ''),
        'HOST': os.environ.get('PROGRAM_DB_HOST', 'localhost'),
        'PORT': os.environ.get('PROGRAM_DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': options,
    }
