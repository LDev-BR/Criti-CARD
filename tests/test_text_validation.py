import re

import pytest

from criticard.validation import FormValidationError, validate_card, validate_profile


def headers(client):
    page = client.get('/feed')
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
    return {'X-CSRF-Token': token, 'Accept': 'application/json'}


@pytest.mark.parametrize('body', ['\0Olá', 'Olá\0', 'Olá\ud800'])
def test_chat_rejects_text_that_database_cannot_store(alice, body):
    auth = headers(alice)
    start = alice.post('/mensagens/iniciar', json={'target_id': 2}, headers=auth)
    assert start.status_code == 201
    conversation = start.json['conversation']['id']
    response = alice.post(f'/mensagens/{conversation}/enviar', headers=auth,
                          json={'body': body, 'client_nonce': 'e9f905b8-727e-4a7c-8673-d23ad58c0a15'})
    assert response.status_code == 400
    assert alice.get(f'/mensagens/{conversation}/historico', headers=auth).json['messages'] == []


def test_comment_rejects_invalid_unicode(alice):
    response = alice.post('/social/cards/1/comments', json={'body': 'Opinião\ud800'}, headers=headers(alice))
    assert response.status_code == 400


@pytest.mark.parametrize('field', ['nome', 'email'])
def test_profile_rejects_nul_before_persistence(field):
    values = dict(username='ALICE', nome='Alice', apelido='Leitora', about='Uma bio', email='alice@example.com')
    values[field] += '\0'
    with pytest.raises(FormValidationError):
        validate_profile(values)


def test_card_rejects_nul_before_persistence():
    with pytest.raises(FormValidationError):
        validate_card(dict(titulo='Uma obra', sobre='Crítica\0', nota='90'))


def test_recovery_invalid_unicode_email_has_generic_response(client):
    response = client.post('/recuperar-senha', json={'email': 'invalid\ud800@example.com'}, headers=headers(client))
    assert response.status_code == 200
    assert 'message' in response.json
