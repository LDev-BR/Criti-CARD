from urllib.parse import urlsplit

from sqlalchemy import delete, insert
from werkzeug.security import generate_password_hash

from criticard.db import delete_user, get_db
from criticard.models import Card, User


def test_cookie_cannot_authenticate_replacement_account_with_reused_id(app, alice):
    with app.app_context():
        delete_user(1)
        with get_db() as db:
            db.execute(insert(User).values(id=1, username='REPLACEMENT', nome='Outra pessoa',
                       apelido='Leitor', about='Outra conta', email='replacement@example.com',
                       senha=generate_password_hash('Password1!')))
    response = alice.get('/dashboard')
    assert response.status_code == 302
    assert urlsplit(response.headers['Location']).path == '/'


def test_legacy_authenticated_cookie_requires_new_login(client):
    with client.session_transaction() as cookie:
        cookie['usuario_id'] = 1
        cookie['session_version'] = 0
    assert client.get('/dashboard').status_code == 302


def test_new_account_and_card_ids_do_not_reuse_deleted_identities(app):
    with app.app_context():
        with get_db() as db:
            values = dict(username='TEMPORARY', nome='Temporária', apelido='Leitor',
                          about='Conta temporária', email='temporary@example.com',
                          senha=generate_password_hash('Password1!'))
            removed_user = db.execute(insert(User).values(**values).returning(User.id)).scalar()
            db.execute(delete(User).where(User.id == removed_user))
            next_user = db.execute(insert(User).values(**values).returning(User.id)).scalar()
            assert next_user > removed_user
            review = dict(titulo='Temporária', capa='temporary.png', sobre='Uma crítica', nota=80, author_id=1)
            removed_card = db.execute(insert(Card).values(**review).returning(Card.id)).scalar()
            db.execute(delete(Card).where(Card.id == removed_card))
            next_card = db.execute(insert(Card).values(**review).returning(Card.id)).scalar()
            assert next_card > removed_card
