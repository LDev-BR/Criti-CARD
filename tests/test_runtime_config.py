import pytest

from criticard import create_app


def production(**changes):
    config = dict(ENVIRONMENT='production', SECRET_KEY='x' * 48,
                  DATABASE_URL='postgresql+psycopg://user@127.0.0.1/unused',
                  SESSION_COOKIE_SECURE=True, DEBUG=False, TRUSTED_HOSTS=['criticard.example'],
                  ACCOUNT_MAIL_BACKEND='smtp', ACCOUNT_BASE_URL='https://criticard.example',
                  ACCOUNT_MAIL_FROM='accounts@criticard.example', ACCOUNT_SMTP_HOST='smtp.example')
    config.update(changes)
    return config


@pytest.mark.parametrize('changes', [dict(SECRET_KEY=None), dict(SECRET_KEY='short'),
    dict(DATABASE_URL=None), dict(SESSION_COOKIE_SECURE=False), dict(DEBUG=True),
    dict(TRUSTED_HOSTS=None), dict(ACCOUNT_MAIL_BACKEND='file'),
    dict(ACCOUNT_BASE_URL='http://criticard.example'), dict(ACCOUNT_SMTP_HOST='')])
def test_public_runtime_refuses_incomplete_configuration(changes):
    with pytest.raises(ValueError):
        create_app(production(**changes))


def test_public_runtime_builds_without_touching_database_or_smtp():
    app = create_app(production())
    assert app.config['SESSION_COOKIE_SECURE']
    app.extensions['database_engine'].dispose()
