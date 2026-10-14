"""Privacy flows use migrated temporary databases and authenticated HTTP clients."""
import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update

from conftest import post, rows
from criticard.chat.models import Conversation, ConversationMember, Message
from criticard.db import get_db
from criticard.models import Card, User
from criticard.security import session_identity
from criticard.social.models import Block, CardLike, Comment, Notification, Report


def member(app, identity=1):
    client = app.test_client()
    client.get('/')
    with app.app_context():
        user = get_db().execute(select(User).where(User.id == identity)).fetchone()
        stamp = session_identity(user)
    with client.session_transaction() as session:
        session.update(usuario_id=identity, session_version=user['session_version'], auth_stamp=stamp)
        token = session['csrf_token']
    return client, token


def test_public_policy_discloses_controller_and_contact_without_login(app):
    app.config['PRIVACY_CONTACT_EMAIL'] = 'privacidade@example.com'
    response = app.test_client().get('/privacidade')
    assert response.status_code == 200
    assert 'Luis Duarte' in response.text
    assert 'mailto:privacidade@example.com' in response.text
    assert '/privacidade/pedidos' in response.text


def test_export_includes_owner_interactions_and_excludes_other_private_content(app):
    with app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Comment).values(author_id=1, card_id=1, body='Meu comentário'))
            db.execute(insert(Comment).values(author_id=2, card_id=1, body='Comentário de outra pessoa'))
            db.execute(insert(CardLike).values(user_id=1, card_id=1))
            db.execute(insert(Block).values(user_id=1, target_id=2))
            db.execute(insert(Block).values(user_id=2, target_id=1))
            db.execute(insert(Notification).values(recipient_id=1, actor_id=2, kind='like', card_id=1,
                event_key='private-notification-key'))
            db.execute(insert(Report).values(reporter_id=1, target_type='user', target_id=2,
                reason='Meu pedido de moderação'))
            db.execute(insert(Report).values(reporter_id=2, target_type='user', target_id=1,
                reason='Denúncia privada de Bob'))
    client, _ = member(app)
    assert post(client, '/mensagem', {'mensagem': 'Meu contato com a equipe'}).status_code == 302
    response = client.get('/configuracoes/conta/exportar')
    assert response.status_code == 200
    data = response.json
    assert [item['body'] for item in data['comments']] == ['Meu comentário']
    assert len(data['likes']) == len(data['blocks']) == len(data['notifications']) == 1
    assert [item['reason'] for item in data['reports']] == ['Meu pedido de moderação']
    assert [item['mensagem'] for item in data['contacts']] == ['Meu contato com a equipe']
    for forbidden in ('Denúncia privada de Bob', 'Comentário de outra pessoa',
            'bob@example.com', 'private-notification-key', 'token_hash', 'senha'):
        assert forbidden not in response.text


def test_account_deletion_removes_sent_text_and_personal_uploads_preserving_others(app):
    with app.app_context():
        db = get_db()
        with db:
            db.execute('UPDATE usuarios SET imagem=? WHERE id=1', ('private-avatar.png',))
            db.execute('UPDATE cards SET capa=? WHERE id=1', ('private-cover.png',))
            db.execute(insert(Card).values(titulo='Card do Bob', capa='shared-cover.png', sobre='Bob',
                nota=80, author_id=2))
            db.execute(insert(Card).values(titulo='Card compartilhado', capa='shared-cover.png', sobre='Alice',
                nota=80, author_id=1))
            conversation = db.execute(insert(Conversation).values(pair_low_id=1, pair_high_id=2)
                .returning(Conversation.id)).scalar()
            for owner in (1, 2):
                db.execute(insert(ConversationMember).values(conversation_id=conversation, user_id=owner))
            sent = db.execute(insert(Message).values(conversation_id=conversation, sender_id=1,
                body='Texto pessoal que precisa sair', client_nonce=str(uuid4())).returning(Message.id)).scalar()
            db.execute(insert(Message).values(conversation_id=conversation, sender_id=2,
                body='Texto do outro participante', client_nonce=str(uuid4())))
            db.execute('UPDATE conversation_members SET last_read_id=? WHERE user_id=2', (sent,))
    for key, name in [('UPLOAD_FOLDER', 'private-avatar.png'), ('CAPA_FOLDER', 'private-cover.png'),
            ('CAPA_FOLDER', 'shared-cover.png')]:
        (Path(app.config[key]) / name).write_bytes(b'fixture image')
    client, _ = member(app)
    assert post(client, '/mensagem', {'mensagem': 'Contato pessoal da Alice'}).status_code == 302
    assert post(client, '/excluir_user', {'senha': 'Password1!'}).status_code == 302
    assert rows(app, 'SELECT id FROM usuarios WHERE id=1') == []
    assert rows(app, 'SELECT body FROM messages') == [{'body': 'Texto do outro participante'}]
    assert rows(app, 'SELECT last_read_id FROM conversation_members WHERE user_id=2') == [{'last_read_id': None}]
    assert rows(app, 'SELECT id FROM contatos') == []
    assert not (Path(app.config['UPLOAD_FOLDER']) / 'private-avatar.png').exists()
    assert not (Path(app.config['CAPA_FOLDER']) / 'private-cover.png').exists()
    assert (Path(app.config['CAPA_FOLDER']) / 'shared-cover.png').exists()


def create_request(client, token, **changes):
    payload = {'kind': 'access', 'body': 'Quero conhecer a origem e as finalidades dos meus dados.'}
    payload.update(changes)
    return client.post('/privacidade/pedidos', json=payload, headers={'X-CSRF-Token': token})


def test_private_requests_ignore_supplied_owner_and_are_visible_only_to_owner(app):
    alice, token = member(app)
    created = create_request(alice, token, user_id=2, status='answered', response='Resposta forjada')
    assert created.status_code == 201
    protocol = created.json['request']['protocol']
    assert re.fullmatch(r'CC-[0-9a-f]{32}', protocol)
    mine = alice.get('/privacidade/pedidos/' + protocol, headers={'Accept': 'application/json'})
    assert mine.status_code == 200 and mine.json['request']['status'] == 'received'
    assert mine.json['request']['replies'] == []
    bob, _ = member(app, 2)
    assert bob.get('/privacidade/pedidos/' + protocol, headers={'Accept': 'application/json'}).status_code == 404
    assert bob.get('/privacidade/pedidos', headers={'Accept': 'application/json'}).json['total'] == 0
    assert alice.get('/privacidade/pedidos', headers={'Accept': 'application/json'}).json['total'] == 1


def test_private_request_pages_and_admin_actions_require_authentication_and_csrf(app):
    anon = app.test_client()
    assert anon.get('/privacidade/pedidos', headers={'Accept': 'application/json'}).status_code == 401
    alice, token = member(app)
    assert alice.post('/privacidade/pedidos', json={'kind': 'access', 'body': 'Dados'}).status_code == 400
    created = create_request(alice, token)
    protocol = created.json['request']['protocol']
    assert alice.get('/admin/privacidade', headers={'Accept': 'application/json'}).status_code == 403
    assert alice.post('/admin/privacidade/' + protocol, json={'status': 'answered', 'body': 'Dados'},
        headers={'X-CSRF-Token': token}).status_code == 403
    admin, admin_token = member(app, 3)
    assert admin.post('/admin/privacidade/' + protocol, json={'status': 'answered', 'body': 'Dados'}).status_code == 400
    assert admin.get('/admin/privacidade/' + protocol).status_code == 200
    answered = admin.post('/admin/privacidade/' + protocol, json={'status': 'answered', 'body': 'Explicação da equipe'},
        headers={'X-CSRF-Token': admin_token})
    assert answered.status_code == 200
    for response in (answered, alice.get('/privacidade/pedidos/' + protocol, headers={'Accept': 'application/json'})):
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        assert response.json['request']['status'] == 'answered'
        assert response.json['request']['replies'][0]['body'] == 'Explicação da equipe'
    assert 'admin@example.com' not in answered.text


@pytest.mark.parametrize('changes', [{'kind': 'invalid'}, {'kind': ['access']}, {'body': ''},
    {'body': 'x' * 3001}, {'body': ['private']}, {'body': 'bad\x00value'}])
def test_invalid_requests_are_not_persisted(app, changes):
    client, token = member(app)
    response = create_request(client, token, **changes)
    assert response.status_code == 422
    assert client.get('/privacidade/pedidos', headers={'Accept': 'application/json'}).json['total'] == 0


def test_request_rate_limit_persists_between_clients_and_does_not_block_reads(app):
    app.config['PRIVACY_REQUEST_ATTEMPT_LIMIT'] = 1
    first, token = member(app)
    assert create_request(first, token).status_code == 201
    second, second_token = member(app, 2)
    response = create_request(second, second_token)
    assert response.status_code == 429 and int(response.headers['Retry-After']) > 0
    assert first.get('/privacidade/pedidos').status_code == 200


def test_admin_keeps_reply_history_and_cannot_close_without_an_explanation(app):
    client, token = member(app)
    protocol = create_request(client, token).json['request']['protocol']
    admin, admin_token = member(app, 3)
    path = '/admin/privacidade/' + protocol
    headers = {'X-CSRF-Token': admin_token}
    assert admin.post(path, json={'status': 'answered', 'body': ''}, headers=headers).status_code == 422
    assert admin.post(path, json={'status': 'in_review', 'body': 'Em verificação'}, headers=headers).status_code == 200
    assert admin.post(path, json={'status': 'answered', 'body': 'Providência concluída'}, headers=headers).status_code == 200
    request_data = client.get('/privacidade/pedidos/' + protocol, headers={'Accept': 'application/json'}).json['request']
    assert [reply['body'] for reply in request_data['replies']] == ['Em verificação', 'Providência concluída']
    assert [reply['status'] for reply in request_data['replies']] == ['in_review', 'answered']


def test_deletion_rechecks_session_after_authentication_and_requires_csrf(app):
    from flask import request
    client, token = member(app)
    assert client.post('/excluir_user', data={'senha': 'Password1!'}).status_code == 400
    def revoke_after_authentication():
        if request.path == '/excluir_user' and request.method == 'POST':
            db = get_db()
            with db:
                db.execute(update(User).where(User.id == 1).values(session_version=1))
    app.before_request_funcs[None].append(revoke_after_authentication)
    response = client.post('/excluir_user', data={'senha': 'Password1!', 'csrf_token': token})
    assert rows(app, 'SELECT id FROM usuarios WHERE id=1') == [{'id': 1}]
    assert response.status_code in (401, 302)


def test_storage_failure_keeps_retryable_deletion_without_retaining_account(app, monkeypatch):
    from criticard.storage import LocalStorage
    from criticard.privacy.models import PendingImageDeletion
    path = Path(app.config['CAPA_FOLDER']) / 'legacy.png'
    path.write_bytes(b'fixture image')
    def unavailable(_storage, _filename):
        raise OSError('Storage unavailable')
    monkeypatch.setattr(LocalStorage, 'remove', unavailable)
    client, token = member(app)
    response = client.post('/excluir_user', data={'senha': 'Password1!', 'csrf_token': token})
    assert response.status_code == 302
    assert rows(app, 'SELECT id FROM usuarios WHERE id=1') == []
    assert path.exists()
    with app.app_context():
        pending = get_db().execute(select(PendingImageDeletion)).fetchone()
        assert pending['filename'] == 'legacy.png'
        assert 'user_id' not in pending and 'email' not in pending
    monkeypatch.undo()
    result = app.test_cli_runner().invoke(args=['privacy-cleanup-images'])
    assert result.exit_code == 0 and not path.exists()
    assert rows(app, 'SELECT id FROM pending_image_deletions') == []


def test_deletion_preserves_legacy_unattributable_text_and_others_reports(app):
    with app.app_context():
        db = get_db()
        with db:
            conversation = db.execute(insert(Conversation).values(pair_low_id=1, pair_high_id=2)
                .returning(Conversation.id)).scalar()
            db.execute(insert(Message).values(conversation_id=conversation, sender_id=None,
                body='Mensagem legada sem autoria', client_nonce=str(uuid4())))
            db.execute('INSERT INTO contatos(nome,email,mensagem) VALUES(?,?,?)',
                ('Identidade legada', 'alice@example.com', 'Contato sem autoria comprovada'))
            db.execute(insert(Report).values(reporter_id=1, target_type='user', target_id=2, reason='Meu relato'))
            db.execute(insert(Report).values(reporter_id=2, target_type='user', target_id=1, reason='Relato de Bob'))
    client, token = member(app)
    protocol = create_request(client, token).json['request']['protocol']
    admin, admin_token = member(app, 3)
    assert admin.post('/admin/privacidade/' + protocol, json={'status': 'answered', 'body': 'Respondido'},
        headers={'X-CSRF-Token': admin_token}).status_code == 200
    assert client.post('/excluir_user', data={'senha': 'Password1!', 'csrf_token': token}).status_code == 302
    assert rows(app, 'SELECT body FROM messages') == [{'body': 'Mensagem legada sem autoria'}]
    assert rows(app, 'SELECT mensagem,user_id FROM contatos') == [
        {'mensagem': 'Contato sem autoria comprovada', 'user_id': None}]
    assert rows(app, 'SELECT reason FROM reports') == [{'reason': 'Relato de Bob'}]
    assert rows(app, 'SELECT id FROM privacy_requests') == rows(app, 'SELECT id FROM privacy_replies') == []


def test_request_free_text_is_escaped_and_not_copied_into_session_cookie(app):
    client, token = member(app)
    private_text = '<script>secret-private-body</script>'
    response = client.post('/privacidade/pedidos', data={'kind': 'access', 'body': private_text,
        'csrf_token': token})
    assert response.status_code == 303
    page = client.get(response.location)
    assert '<script>secret-private-body</script>' not in page.text
    assert '&lt;script&gt;secret-private-body&lt;/script&gt;' in page.text
    with client.session_transaction() as session:
        assert 'secret-private-body' not in str(dict(session))


def test_export_includes_private_request_reply_history_but_not_another_owners_request(app):
    client, token = member(app)
    protocol = create_request(client, token, body='Pedido da Alice').json['request']['protocol']
    bob, bob_token = member(app, 2)
    assert create_request(bob, bob_token, body='Pedido privado de Bob').status_code == 201
    admin, admin_token = member(app, 3)
    assert admin.post('/admin/privacidade/' + protocol, json={'status': 'answered', 'body': 'Resposta para Alice'},
        headers={'X-CSRF-Token': admin_token}).status_code == 200
    response = client.get('/configuracoes/conta/exportar')
    assert len(response.json['privacy_requests']) == 1
    request_data = response.json['privacy_requests'][0]
    assert request_data['body'] == 'Pedido da Alice'
    assert request_data['replies'][0]['body'] == 'Resposta para Alice'
    assert 'Pedido privado de Bob' not in response.text and 'admin@example.com' not in response.text


def test_pagination_is_bounded_and_filters_admin_queue_without_leaking_ownership(app):
    from criticard.privacy.models import PrivacyRequest
    with app.app_context():
        db = get_db()
        with db:
            for index in range(22):
                db.execute(insert(PrivacyRequest).values(user_id=1 if index < 21 else 2,
                    protocol='CC-' + f'{index:032x}', kind='access', body='Pedido',
                    status='answered' if index < 2 else 'received'))
    client, _ = member(app)
    data = client.get('/privacidade/pedidos?page=9999999', headers={'Accept': 'application/json'}).json
    assert data['total'] == 21 and data['page'] == data['pages'] == 2 and len(data['requests']) == 1
    assert 'owner' not in str(data)
    assert client.get('/privacidade/pedidos?page=bad').status_code == 200
    admin, _ = member(app, 3)
    data = admin.get('/admin/privacidade?status=answered', headers={'Accept': 'application/json'}).json
    assert data['total'] == 2 and all(item['status'] == 'answered' for item in data['requests'])


def test_upgrade_from_0008_preserves_legacy_contacts_messages_and_settings(app):
    from alembic import command
    from alembic.config import Config
    from criticard.config import ROOT
    from criticard.db import upgrade_database
    from criticard.settings.service import get_preferences, save_preferences
    engine = app.extensions['database_engine']
    config = Config()
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.downgrade(config, '0008_user_settings')
    with app.app_context():
        db = get_db()
        with db:
            db.execute('INSERT INTO contatos(nome,email,mensagem) VALUES(?,?,?)',
                ('Histórico', 'legacy@example.com', 'Preservar para avaliação'))
            conversation = db.execute('INSERT INTO conversations(pair_low_id,pair_high_id,created_at) '
                'VALUES(1,2,CURRENT_TIMESTAMP) RETURNING id').scalar()
            db.execute('INSERT INTO messages(conversation_id,sender_id,body,created_at,client_nonce) '
                'VALUES(?,NULL,?,CURRENT_TIMESTAMP,?)', (conversation,'Texto legado',str(uuid4())))
        save_preferences(1, 'chat', {'chat_preview': False})
        upgrade_database()
        upgrade_database()
        assert db.execute('SELECT version_num FROM alembic_version').scalar() == '0016_discovery_follows'
        assert db.execute('SELECT COUNT(*) FROM obras WHERE active=1').scalar() == 30
        assert db.execute('SELECT mensagem,user_id FROM contatos').fetchall() == [
            {'mensagem': 'Preservar para avaliação', 'user_id': None}]
        assert db.execute('SELECT body FROM messages').fetchall() == [{'body': 'Texto legado'}]
        assert get_preferences(1)['chat_preview'] is False
        assert db.execute('SELECT COUNT(*) FROM usuarios').scalar() == 3
