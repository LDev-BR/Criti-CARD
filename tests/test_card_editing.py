import io
from pathlib import Path

import pytest

from conftest import image_file, post, rows


def test_author_can_open_edit_with_existing_values(alice, app):
    (Path(app.config['CAPA_FOLDER']) / 'legacy.png').write_bytes(image_file()[0].getvalue())
    response = alice.get('/editar_card/1')
    assert response.status_code == 200
    assert 'Card da Alice' in response.text
    assert 'Uma boa historia' in response.text
    assert 'legacy.png' in response.text
    assert alice.get('/media/cover/legacy.png').status_code == 200


def test_author_edit_preserves_cover_without_new_upload(alice, app):
    response = post(alice, '/editar_card/1', {'titulo':'Berserk', 'sobre':'Uma critica revisada', 'nota':'100'})
    assert response.status_code == 302
    card = rows(app, 'SELECT * FROM cards WHERE id=1')[0]
    assert (card['titulo'], card['sobre'], card['nota'], card['capa'], card['author_id']) == (
        'Berserk', 'Uma critica revisada', 100, 'legacy.png', 1)


def test_author_edit_ignores_personal_cover(alice, app):
    response = post(alice, '/editar_card/1', {'titulo':'Berserk', 'sobre':'Nova critica', 'nota':'75',
                                           'capa':image_file()})
    assert response.status_code == 302
    card = rows(app, 'SELECT capa,sobre FROM cards WHERE id=1')[0]
    assert card['capa'] == 'legacy.png' and card['sobre'] == 'Nova critica'
    assert list(Path(app.config['CAPA_FOLDER']).iterdir()) == []


@pytest.mark.parametrize('score', ['-1','101','nope'])
def test_invalid_edit_preserves_database_and_form_values(alice, app, score):
    response = post(alice, '/editar_card/1', {'titulo':'Alterado', 'sobre':'Texto mantido', 'nota':score,
                                           'capa':image_file()})
    assert response.status_code == 200
    assert 'Alterado' in response.text and 'Texto mantido' in response.text
    assert rows(app, 'SELECT titulo FROM cards WHERE id=1')[0][0] == 'Card da Alice'
    assert list(Path(app.config['CAPA_FOLDER']).iterdir()) == []


def test_other_user_cannot_open_or_submit_edit(client, app):
    post(client, '/', {'username':'bob', 'senha':'Password1!'})
    assert client.get('/editar_card/1').status_code == 403
    assert post(client, '/editar_card/1', {'titulo':'Roubo','sobre':'Texto','nota':'0'}).status_code == 403
    assert rows(app, 'SELECT titulo FROM cards WHERE id=1')[0][0] == 'Card da Alice'


def test_anonymous_edit_requires_login(client):
    assert client.get('/editar_card/1').status_code == 302


def test_edit_requires_csrf(alice, app):
    assert alice.post('/editar_card/1',data={'titulo':'Alterado','sobre':'Texto','nota':'50'}).status_code == 400
    assert rows(app, 'SELECT titulo FROM cards WHERE id=1')[0][0] == 'Card da Alice'


def test_irrelevant_invalid_upload_does_not_block_valid_edit(alice, app):
    response = post(alice, '/editar_card/1', {'titulo':'Alterado', 'sobre':'Texto', 'nota':'50',
                                           'capa':(io.BytesIO(b'bad image'), 'bad.png')})
    assert response.status_code == 302
    assert rows(app, 'SELECT capa FROM cards WHERE id=1')[0][0] == 'legacy.png'
    assert rows(app, 'SELECT titulo,sobre FROM cards WHERE id=1')[0] == {'titulo':'Alterado','sobre':'Texto'}
    assert list(Path(app.config['CAPA_FOLDER']).iterdir()) == []


def test_full_review_has_public_fallback_without_private_data(client):
    response = client.get('/card/1')
    assert response.status_code == 200
    assert 'Uma boa historia' in response.text
    assert 'ALICE' in response.text
    assert 'alice@example.com' not in response.text
    assert 'Editar card' not in response.text
    assert 'Excluir card' not in response.text


def test_missing_edit_or_detail_returns_404(alice):
    assert alice.get('/editar_card/999').status_code == 404
    assert alice.get('/card/999').status_code == 404
