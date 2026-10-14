"""Review deployment contracts without starting Docker, SMTP or cloud services."""
import os
import shutil
import subprocess

import pytest
import yaml

from criticard import create_app
from criticard.config import ROOT


def deployment():
    path = ROOT / 'compose.yaml'
    assert path.is_file(), 'The reviewed production Compose configuration is missing'
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def test_compose_preserves_postgres18_data_and_keeps_database_off_host_ports():
    config = deployment()
    database = config['services']['postgres']
    assert database['image'].split(':')[-1].split('-')[0] == '18'
    assert 'ports' not in database
    assert any(volume.split(':')[1] == '/var/lib/postgresql' for volume in database['volumes'])
    assert 'POSTGRES_PASSWORD' in database['environment']
    assert ':?' in database['environment']['POSTGRES_PASSWORD']


def test_compose_starts_app_after_migrations_and_shares_private_mail_spool():
    config = deployment()
    services = config['services']
    assert services['app']['depends_on']['migrate']['condition'] == 'service_completed_successfully'
    assert services['migrate']['depends_on']['postgres']['condition'] == 'service_healthy'
    assert services['migrate']['command'] == ['python', '-m', 'flask', '--app', 'app', 'db-upgrade']
    app_volumes = set(services['app']['volumes'])
    worker = services['mail-worker']
    assert worker['command'] == ['python', '-m', 'criticard.accounts.worker']
    assert 'account_outbox:/app/instance/outbox' in app_volumes.intersection(worker['volumes'])
    assert services['app']['environment']['ACCOUNT_OUTBOX_PATH'] == '/app/instance/outbox'
    assert 'ports' not in services['app']
    assert services['app']['read_only'] is True
    assert services['app']['cap_drop'] == ['ALL']


def test_compose_cli_validates_configuration_without_loading_real_env_files(tmp_path):
    compose = shutil.which('docker-compose')
    docker = shutil.which('docker')
    if compose is None and docker is None:
        pytest.skip('Docker CLI is not installed; semantic Compose checks still run')
    docker_config = tmp_path / 'docker-config'
    docker_config.mkdir()
    (docker_config / 'config.json').write_text('{}', encoding='utf-8')
    env_file = tmp_path / 'synthetic.env'
    env_file.write_text('SECRET_KEY=' + 'x' * 64 + '\n'
        'POSTGRES_PASSWORD=test-only-password\n'
        'DATABASE_URL=postgresql+psycopg://test_only@postgres:5432/test_only\n'
        'HEALTHCHECK_HOST=criticard.example.test\n', encoding='utf-8')
    environment = {**os.environ, 'SECRET_KEY': 'x' * 64, 'POSTGRES_PASSWORD': 'test-only-password',
        'DATABASE_URL': 'postgresql+psycopg://test_only@postgres:5432/test_only',
        'HEALTHCHECK_HOST': 'criticard.example.test', 'DOCKER_CONFIG': str(docker_config)}
    command = [compose] if compose else [docker, '--config', str(docker_config), 'compose']
    result = subprocess.run([*command,
        '--file', str(ROOT / 'compose.yaml'), '--env-file', str(env_file),
        'config', '--no-env-resolution', '--quiet'], cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_valid_production_configuration_does_not_connect_or_migrate_on_creation(tmp_path):
    config = {'ENVIRONMENT': 'production', 'TESTING': False, 'SECRET_KEY': 'x' * 64,
        'DATABASE_URL': 'postgresql+psycopg://test_only@127.0.0.1:9/test_only',
        'DATABASE': str(tmp_path / 'unused.db'), 'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
        'CAPA_FOLDER': str(tmp_path / 'covers'), 'SESSION_COOKIE_SECURE': True, 'DEBUG': False,
        'TRUSTED_HOSTS': ['criticard.example.test'], 'ACCOUNT_BASE_URL': 'https://criticard.example.test',
        'ACCOUNT_MAIL_BACKEND': 'smtp', 'ACCOUNT_MAIL_FROM': 'noreply@example.test',
        'ACCOUNT_SMTP_HOST': 'smtp.example.test', 'ACCOUNT_SMTP_TLS': 'starttls',
        'ACCOUNT_OUTBOX_PATH': str(tmp_path / 'private-outbox'), 'STORAGE_BACKEND': 'local'}
    application = create_app(config)
    try:
        assert application.config['SESSION_COOKIE_SECURE'] is True
        assert not application.debug
        assert not (tmp_path / 'unused.db').exists()
        assert list((tmp_path / 'private-outbox').glob('*.eml')) == []
    finally:
        application.extensions['database_engine'].dispose()


@pytest.mark.parametrize('override', [
    {'SESSION_COOKIE_SECURE': False}, {'SECRET_KEY': 'too-short'},
    {'DATABASE_URL': 'sqlite:///unused.db'}, {'DEBUG': True},
    {'ACCOUNT_BASE_URL': 'http://criticard.example.test'}, {'ACCOUNT_MAIL_BACKEND': 'outbox'},
])
def test_production_rejects_configuration_that_would_break_security_or_account_delivery(tmp_path, override):
    config = {'ENVIRONMENT': 'production', 'TESTING': False, 'SECRET_KEY': 'x' * 64,
        'DATABASE_URL': 'postgresql+psycopg://test_only@127.0.0.1:9/test_only',
        'DATABASE': str(tmp_path / 'unused.db'), 'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
        'CAPA_FOLDER': str(tmp_path / 'covers'), 'SESSION_COOKIE_SECURE': True, 'DEBUG': False,
        'TRUSTED_HOSTS': ['criticard.example.test'], 'ACCOUNT_BASE_URL': 'https://criticard.example.test',
        'ACCOUNT_MAIL_BACKEND': 'smtp', 'ACCOUNT_MAIL_FROM': 'noreply@example.test',
        'ACCOUNT_SMTP_HOST': 'smtp.example.test', 'ACCOUNT_SMTP_TLS': 'starttls',
        'ACCOUNT_OUTBOX_PATH': str(tmp_path / 'private-outbox'), 'STORAGE_BACKEND': 'local', **override}
    with pytest.raises(ValueError):
        application = create_app(config)
        application.extensions['database_engine'].dispose()
