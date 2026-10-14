"""Personal connection pages share the same authenticated relationships."""
from sqlalchemy import insert, select

from criticard.db import get_db
from criticard.models import User
from criticard.social.models import Block, Follow
from test_chat import app, action, member


def seed_outgoing_pages(app):
    from criticard.social.connections import change_friendship
    with app.app_context():
        db = get_db()
        password_hash = db.execute(select(User.senha).where(User.id == 1)).scalar()
        with db:
            db.execute(insert(User), [dict(id=identity, username=f'PERSON{identity}',
                nome=f'Pessoa{identity:02}', apelido='Leitor', about='', email=f'person{identity}@example.com',
                senha=password_hash) for identity in range(4, 29)])
        for identity in range(4, 29):
            change_friendship(1, identity, 'request')


def test_connections_require_login_and_csrf(app):
    assert app.test_client().get('/conexoes', headers={'Accept': 'application/json'}).status_code == 401
    client, _ = member(app, 1)
    assert client.post('/conexoes/2/amizade', json={'action': 'request'}).status_code == 400


def test_request_pages_are_owned_by_the_session_and_accept_does_not_follow(app):
    alice, token = member(app, 1)
    bob, bob_token = member(app, 2)
    admin, _ = member(app, 3)
    sent = action(alice, token, '/conexoes/2/amizade', {'action': 'request'})
    assert sent.status_code == 200
    assert sent.json['friendship']['state'] == 'outgoing'
    assert [p['username'] for p in bob.get('/conexoes?aba=recebidas', headers={'Accept': 'application/json'}).json['people']] == ['ALICE']
    assert admin.get('/conexoes?aba=recebidas&user_id=2', headers={'Accept': 'application/json'}).json['people'] == []
    assert action(alice, token, '/conexoes/2/amizade', {'action': 'accept'}).status_code == 403
    accepted = action(bob, bob_token, '/conexoes/1/amizade', {'action': 'accept'})
    assert accepted.status_code == 200
    assert accepted.json['friendship']['state'] == 'friends'
    assert alice.get('/conexoes?aba=amigos', headers={'Accept': 'application/json'}).json['counts']['friends'] == 1
    with app.app_context():
        assert get_db().execute(select(Follow.id)).fetchone() is None


def test_discovery_is_searchable_public_data_and_filters_bilateral_blocks(app):
    client, _ = member(app, 1)
    response = client.get('/conexoes?aba=descobrir&q=Bob', headers={'Accept': 'application/json'})
    assert response.status_code == 200
    assert [p['username'] for p in response.json['people']] == ['BOB']
    assert response.json['people'][0]['avatar_url']
    assert not {'senha', 'email', 'session_version', 'admin', 'active'} & response.json['people'][0].keys()
    with app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Block).values(user_id=2, target_id=1))
    assert client.get('/conexoes?aba=descobrir&q=Bob', headers={'Accept': 'application/json'}).json['people'] == []


def test_connection_forms_redirect_locally_and_validate_actions(app):
    client, token = member(app, 1)
    response = client.post('/conexoes/2/amizade', data={
        'csrf_token': token, 'action': 'request', 'return_to': 'https://evil.example/'})
    assert response.status_code == 302
    assert response.location.startswith('/conexoes')
    assert action(client, token, '/conexoes/2/amizade', {'action': 'invalid'}).status_code == 400
    assert action(client, token, '/conexoes/2/amizade', {'action': ['accept']}).status_code == 400


def test_connection_pages_explain_empty_states_and_preserve_filters(app):
    client, _ = member(app, 1)
    response = client.get('/conexoes?aba=amigos')
    assert response.status_code == 200
    assert 'Seus amigos' in response.text
    assert 'Encontrar pessoas' in response.text
    for tab in ('recebidas', 'enviadas', 'seguindo', 'seguidores', 'descobrir'):
        page = client.get('/conexoes?aba=' + tab)
        assert page.status_code == 200
        assert 'data-connections-fragment' in page.text


def test_last_page_mutation_without_js_preserves_query_and_returns_to_valid_page(app):
    from urllib.parse import parse_qs, urlsplit
    seed_outgoing_pages(app)
    client, token = member(app, 1)
    assert client.get('/conexoes?aba=enviadas&q=Pessoa&page=2').status_code == 200
    response = client.post('/conexoes/28/amizade', data={'csrf_token': token,
        'action': 'cancel', 'aba': 'enviadas', 'q': 'Pessoa', 'page': '2'})
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.location).query) == {'aba': ['enviadas'], 'q': ['Pessoa'], 'page': ['1']}
    assert client.get(response.location).status_code == 200
