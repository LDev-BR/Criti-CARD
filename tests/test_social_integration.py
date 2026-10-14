import pytest
from sqlalchemy import insert

from conftest import post
from criticard.db import get_db
from criticard.models import Card
from criticard.social.models import Comment


def bob_card(app):
    with app.app_context():
        with get_db() as db:
            return db.execute(insert(Card).values(titulo='Obra do Bob', capa='cover.png',
                sobre='Outra perspectiva', nota=88, author_id=2, obra_id=1).returning(Card.id)).scalar()


def test_following_feed_preserves_filters_and_excludes_other_authors(app, alice):
    identity = bob_card(app)
    assert post(alice, '/social/users/2/follow', {'following': 'true'}).status_code == 302
    page = alice.get('/criticas?feed=following&categoria=jogos&nota_min=80')
    assert page.status_code == 200
    assert 'data-title="Elden Ring"' in page.text
    assert f'id="card-{identity}"' in page.text
    assert 'data-title="Card da Alice"' not in page.text
    assert 'name="feed" value="following"' in page.text
    assert 'feed=following' in page.text


def test_block_hides_reviews_and_comments_across_entry_points(app, alice):
    identity = bob_card(app)
    assert f'id="card-{identity}"' in alice.get('/criticas').text
    assert post(alice, '/social/users/2/block', {'blocked': 'true'}).status_code == 302
    assert f'id="card-{identity}"' not in alice.get('/criticas').text
    assert f'id="card-{identity}"' not in alice.get('/perfil/BOB').text
    assert alice.get(f'/card/{identity}').status_code == 404
    assert alice.get(f'/social/cards/{identity}/comments').status_code == 404


def test_following_feed_requires_authentication(client):
    assert client.get('/criticas?feed=following').status_code == 302


@pytest.mark.parametrize('blocker,target', [(1, 2), (2, 1)])
def test_blocked_comments_are_hidden_in_detail_fragments_and_counts(app, alice, blocker, target):
    from criticard.social.models import Block

    with app.app_context():
        with get_db() as db:
            db.execute(insert(Comment), [
                {'card_id': 1, 'author_id': 2, 'body': 'Comentario bloqueado'}
                for _ in range(31)
            ])
            db.execute(insert(Comment).values(card_id=1, author_id=1, body='Comentario visivel'))
            db.execute(insert(Block).values(user_id=blocker, target_id=target))

    for route in ('/card/1', '/social/cards/1/comments'):
        response = alice.get(route)
        assert response.status_code == 200
        assert 'Comentario visivel' in response.text
        assert 'Comentario bloqueado' not in response.text

    response = alice.get('/social/cards/1/comments', headers={'Accept': 'application/json'})
    assert response.json['total'] == 1
    assert response.json['pages'] == 1
    assert len(response.json['comments']) == 1
    assert alice.get('/social/cards/1/comments?page=2').status_code == 404
    with app.test_request_context('/criticas'):
        from flask import g
        from criticard.social.service import card_social_state
        g.user = {'id': 1}
        assert card_social_state([1], 1)[1]['comment_count'] == 1

    # Blocking changes the viewer's visibility without erasing public comments.
    guest = app.test_client()
    public = guest.get('/social/cards/1/comments', headers={'Accept': 'application/json'})
    assert public.json['total'] == 32


def test_unblocking_restores_comment_visibility(app, alice):
    with app.app_context():
        with get_db() as db:
            db.execute(insert(Comment).values(card_id=1, author_id=2, body='Comentario recuperado'))
    assert post(alice, '/social/users/2/block', {'blocked': 'true'}).status_code == 302
    assert 'Comentario recuperado' not in alice.get('/card/1').text
    assert post(alice, '/social/users/2/block', {'blocked': 'false'}).status_code == 302
    assert 'Comentario recuperado' in alice.get('/card/1').text
