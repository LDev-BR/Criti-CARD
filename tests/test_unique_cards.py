"""A review is updated rather than published twice for the same author/work."""
import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from criticard.db import get_db
from criticard.models import Card
from criticard.social.models import Comment
from conftest import post, rows


def publish(client, work='1', body='Minha experiência'):
    return post(client, '/cadastro_cards', {'obra_id':work, 'sobre':body, 'nota':'90'})


def test_second_publication_is_blocked_and_keeps_the_draft(alice, app):
    assert publish(alice).status_code == 302
    response = publish(alice, body='Meu texto deve continuar aqui')
    assert response.status_code == 200
    assert 'obra_id-error' in response.text and 'Meu texto deve continuar aqui' in response.text
    assert '/editar_card/2' in response.text
    assert rows(app, 'SELECT COUNT(*) FROM cards')[0][0] == 2


def test_other_author_can_review_the_same_work(alice, client, app):
    assert publish(alice).status_code == 302
    assert post(client, '/', {'username':'bob', 'senha':'Password1!'}).status_code == 302
    assert publish(client).status_code == 302
    assert rows(app, 'SELECT COUNT(*) FROM cards WHERE obra_id=1')[0][0] == 2


def test_edit_cannot_move_another_review_to_an_already_reviewed_work(alice, app):
    publish(alice)
    publish(alice, '2')
    response = post(alice, '/editar_card/3', {'obra_id':'1', 'sobre':'Texto preservado', 'nota':'99'})
    assert response.status_code == 200 and 'obra_id-error' in response.text
    card = rows(app, 'SELECT obra_id,sobre FROM cards WHERE id=3')[0]
    assert card == {'obra_id':2,'sobre':'Minha experiência'}
    assert post(alice, '/editar_card/2', {'obra_id':'1','sobre':'Reavaliada','nota':'99'}).status_code == 302


@pytest.mark.parametrize('retired', [False, True])
def test_preselected_work_opens_its_existing_review(alice, app, retired):
    publish(alice)
    if retired:
        with app.app_context():
            with get_db() as db:
                db.execute('UPDATE obras SET active=0 WHERE id=1')
    response = alice.get('/cadastro_cards?obra_id=1')
    assert response.status_code == 302 and response.location.endswith('/editar_card/2')


def test_database_rejects_duplicate_published_review(alice, app):
    publish(alice)
    with app.app_context():
        with pytest.raises(IntegrityError):
            with get_db() as db:
                db.execute(insert(Card).values(author_id=1, obra_id=1, titulo='Outra',
                    capa='default-cover.svg', sobre='Duplicada', nota=80))


def test_archived_review_is_private_and_cannot_accept_new_interactions(alice, app):
    client = app.test_client()
    publish(alice)
    with app.app_context():
        with get_db() as db:
            db.execute('UPDATE cards SET archived=1 WHERE id=2')
    assert client.get('/card/2').status_code == 404
    assert 'id="card-2"' not in client.get('/criticas').text
    assert 'id="card-2"' not in client.get('/perfil/ALICE').text
    assert alice.get('/card/2').status_code == 200
    assert 'Histórico privado' in alice.get('/card/2').text
    assert 'id="card-2"' in alice.get('/dashboard?aba=arquivados').text
    assert client.get('/social/cards/2/comments').status_code == 404
    assert post(alice, '/social/cards/2/like', {'liked':'true'}).status_code == 404
    assert post(alice, '/social/cards/2/comments', {'body':'Novo comentário'}).status_code == 404
    assert publish(alice).status_code == 302


def test_archived_review_keeps_its_original_identity_and_can_read_all_comments(alice, app):
    publish(alice)
    with app.app_context():
        with get_db() as db:
            db.execute('UPDATE cards SET archived=1 WHERE id=2')
            db.execute("UPDATE obras SET titulo='Renomeada',search_title='renomeada' WHERE id=1")
            for number in range(31):
                db.execute(insert(Comment).values(author_id=2, card_id=2, body=f'Comentário {number}'))
    first = alice.get('/card/2')
    assert 'Elden Ring' in first.text and 'Renomeada' not in first.text
    assert 'comments_page=2' in first.text
    second = alice.get('/card/2?comments_page=2')
    assert second.status_code == 200 and 'Comentário 0' in second.text
    assert alice.get('/card/2?comments_page=100').status_code == 404
    exported = alice.get('/configuracoes/conta/exportar').json
    assert next(card for card in exported['cards'] if card['id'] == 2)['archived'] == 1


def test_comment_author_can_erase_own_archived_text_but_cannot_open_an_unusable_editor(alice, app):
    publish(alice)
    with app.app_context():
        with get_db() as db:
            comment_id = db.execute(insert(Comment).values(author_id=2,card_id=2,body='Meu comentário pessoal').returning(Comment.id)).scalar()
            db.execute('UPDATE cards SET archived=1 WHERE id=2')
    bob = app.test_client()
    post(bob, '/', {'username':'bob','senha':'Password1!'})
    assert bob.get(f'/social/comments/{comment_id}/edit').status_code == 404
    assert post(bob, f'/social/comments/{comment_id}/delete', {}).status_code == 302
    assert rows(app, 'SELECT COUNT(*) FROM comments WHERE id=?', (comment_id,))[0][0] == 0
