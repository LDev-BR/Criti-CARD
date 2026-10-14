"""Authentication resumes a user journey without accepting external redirects."""
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import post


def test_protected_read_resumes_after_login(client):
    response = client.get('/privacidade/pedidos')
    assert parse_qs(urlsplit(response.location).query)['next'] == ['/privacidade/pedidos']
    login = post(client, '/?next=/privacidade/pedidos', {'username': 'alice', 'senha': 'Password1!'})
    assert login.location == '/privacidade/pedidos'


@pytest.mark.parametrize('destination', ['https://evil.example/', '//evil.example/', '/\\evil.example/',
    '/%5cevil.example/', '/%2fevil.example/', '/%252fevil.example/', '/%0aevil.example/', '/'])
def test_login_rejects_unsafe_or_looping_destination(client, destination):
    response = post(client, '/', {'username': 'alice', 'senha': 'Password1!', 'next': destination})
    assert response.location == '/dashboard'


def test_logged_in_user_can_follow_login_return_link(alice):
    assert alice.get('/?next=/catalogo?categoria=jogos').location == '/catalogo?categoria=jogos'


def test_unauthenticated_write_does_not_become_a_get_destination(client):
    response = post(client, '/deletar_card/1')
    assert response.status_code == 302 and 'next=' not in response.location
