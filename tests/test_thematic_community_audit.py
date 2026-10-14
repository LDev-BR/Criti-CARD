"""Community input and membership regressions using disposable migrated databases."""
import re

import pytest
from sqlalchemy import delete, insert, select, update

from criticard.communities import service
from criticard.communities.models import (
    Community, CommunityComment, CommunityMembership, CommunityPost,
)
from criticard.db import get_db
from criticard.models import User, Work
from criticard.security import session_identity


@pytest.fixture
def community_data(app):
    # The shared app fixture points exclusively at tmp_path / test.db.
    with app.app_context():
        db = get_db()
        with db:
            community = db.execute(select(Community.__table__).where(
                Community.slug == 'tema-animes')).fetchone()
            for user_id, role in ((1, 'owner'), (2, 'member')):
                db.execute(insert(CommunityMembership).values(
                    community_id=community['id'], user_id=user_id, role=role))
            post_id = db.execute(insert(CommunityPost).values(
                community_id=community['id'], author_id=2,
                title='Conversa original', body='Publicacao original').returning(
                    CommunityPost.id)).scalar()
            comment_id = db.execute(insert(CommunityComment).values(
                post_id=post_id, author_id=2, body='Comentario original').returning(
                    CommunityComment.id)).scalar()
    return {'community_id': community['id'], 'slug': community['slug'],
            'post_id': post_id, 'comment_id': comment_id}


def member(app, user_id):
    client = app.test_client()
    page = client.get('/')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token, 'CSRF token must come from a rendered form'
    with app.app_context():
        user = get_db().execute(select(User).where(User.id == user_id)).fetchone()
        identity = session_identity(user)
    with client.session_transaction() as session:
        session['usuario_id'] = user_id
        session['session_version'] = user['session_version']
        session['auth_stamp'] = identity
    return client, token.group(1)


def action(client, token, path, data=None):
    return client.post(path, data=data or {}, headers={'X-CSRF-Token': token})


@pytest.mark.parametrize('identifier, expected_status', [
    (str(2 ** 63), 422),
    pytest.param('9' * 5000, 404, id='unbounded-number'),
])
def test_oversized_publication_url_returns_client_error(
        app, community_data, identifier, expected_status):
    path = f"/comunidades/{community_data['slug']}/publicacoes/{identifier}"
    assert app.test_client().get(path).status_code == expected_status


@pytest.mark.parametrize('path', [
    '/tema-animes/publicacoes/{invalid}/comentar',
    '/publicacoes/{invalid}/reagir/like',
    '/publicacoes/{invalid}/excluir',
    '/publicacoes/{invalid}/editar',
    '/comentarios/{invalid}/excluir',
    '/comentarios/{invalid}/editar',
    '/solicitacoes/{invalid}/aprovar',
    '/solicitacoes/{invalid}/cancelar',
    '/convites/{invalid}/aceitar',
    '/tema-animes/membros/{invalid}/papel',
    '/tema-animes/membros/{invalid}/remover',
])
def test_oversized_mutation_identifiers_return_validation_error(app, community_data, path):
    client, token = member(app, 1)
    response = action(client, token, '/comunidades' + path.format(invalid=2 ** 63),
                      {'title': 'Novo titulo', 'body': 'Novo texto', 'role': 'member'})
    assert response.status_code == 422


@pytest.mark.parametrize('operation', ['create', 'edit'])
@pytest.mark.parametrize('work_id', [str(2 ** 63), '0', '-1'])
def test_invalid_work_identifiers_do_not_change_publications(
        app, community_data, operation, work_id):
    client, token = member(app, 2)
    path = (f"/comunidades/{community_data['slug']}/publicar" if operation == 'create'
            else f"/comunidades/publicacoes/{community_data['post_id']}/editar")
    response = action(client, token, path,
                      {'title': 'Novo titulo', 'body': 'Novo texto', 'work_id': work_id})
    assert response.status_code == 422
    with app.app_context():
        posts = get_db().execute(select(CommunityPost.__table__)).fetchall()
        assert len(posts) == 1
        assert posts[0]['title'] == 'Conversa original'
        assert posts[0]['body'] == 'Publicacao original'
        assert posts[0]['work_id'] is None


@pytest.mark.parametrize('departure', ['leave', 'remove'])
def test_comment_author_cannot_edit_after_losing_membership(app, community_data, departure):
    with app.app_context():
        if departure == 'leave':
            service.leave_community(2, community_data['community_id'])
        else:
            service.remove_member(1, community_data['community_id'], 2)
    client, token = member(app, 2)
    response = action(client, token,
                      f"/comunidades/comentarios/{community_data['comment_id']}/editar",
                      {'body': 'Comentario alterado'})
    assert response.status_code == 403
    page = client.get(f"/comunidades/{community_data['slug']}/publicacoes/"
                      f"{community_data['post_id']}")
    assert page.status_code == 200
    assert f'/comunidades/comentarios/{community_data["comment_id"]}/editar' not in page.text
    assert f'/comunidades/publicacoes/{community_data["post_id"]}/editar' not in page.text
    assert f'/comunidades/publicacoes/{community_data["post_id"]}/reagir/' not in page.text
    assert f'/comunidades/comentarios/{community_data["comment_id"]}/excluir' in page.text
    assert 'Denunciar comentário' in page.text
    assert 'Denunciar publicação' in page.text
    with app.app_context():
        assert get_db().execute(select(CommunityComment.body).where(
            CommunityComment.id == community_data['comment_id'])).scalar() == 'Comentario original'


def test_current_member_can_edit_own_comment(app, community_data):
    client, token = member(app, 2)
    page = client.get(f"/comunidades/{community_data['slug']}/publicacoes/"
                      f"{community_data['post_id']}")
    assert page.status_code == 200
    assert f'/comunidades/comentarios/{community_data["comment_id"]}/editar' in page.text
    assert f'/comunidades/publicacoes/{community_data["post_id"]}/editar' in page.text
    assert f'/comunidades/publicacoes/{community_data["post_id"]}/reagir/' in page.text
    response = action(client, token,
                      f"/comunidades/comentarios/{community_data['comment_id']}/editar",
                      {'body': 'Comentario alterado'})
    assert response.status_code == 302
    with app.app_context():
        assert get_db().execute(select(CommunityComment.body).where(
            CommunityComment.id == community_data['comment_id'])).scalar() == 'Comentario alterado'


def test_form_publication_can_link_and_clear_a_valid_catalog_work(app, community_data):
    with app.app_context():
        category_id = get_db().execute(select(Community.category_id).where(
            Community.id == community_data['community_id'])).scalar()
        work_id = get_db().execute(select(Work.id).where(
            Work.categoria_id == category_id, Work.active == 1).limit(1)).scalar()
    assert work_id is not None
    client, token = member(app, 2)
    response = action(client, token, f"/comunidades/{community_data['slug']}/publicar",
                      {'title': 'Obra selecionada', 'body': 'Uma conversa', 'work_id': str(work_id)})
    assert response.status_code == 302
    with app.app_context():
        post_id = get_db().execute(select(CommunityPost.id).where(
            CommunityPost.title == 'Obra selecionada')).scalar()
        assert get_db().execute(select(CommunityPost.work_id).where(
            CommunityPost.id == post_id)).scalar() == work_id
    response = action(client, token, f'/comunidades/publicacoes/{post_id}/editar',
                      {'title': 'Obra selecionada', 'body': 'Uma conversa', 'work_id': ''})
    assert response.status_code == 302
    with app.app_context():
        assert get_db().execute(select(CommunityPost.work_id).where(
            CommunityPost.id == post_id)).scalar() is None


def test_closed_community_content_stays_private_after_departure(app, community_data):
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(Community).where(Community.id == community_data['community_id']).values(
                mode='closed', description='Descricao confidencial'))
            db.execute(delete(CommunityMembership).where(
                CommunityMembership.community_id == community_data['community_id'],
                CommunityMembership.user_id == 2))
    client, token = member(app, 2)
    detail = client.get(f"/comunidades/{community_data['slug']}")
    assert detail.status_code == 200
    for private_text in ('Descricao confidencial', 'Publicacao original', 'Comentario original', '@ALICE'):
        assert private_text not in detail.text
    assert client.get(f"/comunidades/{community_data['slug']}/publicacoes/"
                      f"{community_data['post_id']}").status_code == 403
    assert action(client, token,
                  f"/comunidades/comentarios/{community_data['comment_id']}/editar",
                  {'body': 'Novo texto'}).status_code == 403
