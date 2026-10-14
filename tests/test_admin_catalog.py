"""Catalog administration preserves history and authorizes locked accounts."""
from pathlib import Path

import pytest
from flask import request
from sqlalchemy import insert, select, update
from werkzeug.exceptions import Forbidden, NotFound
from werkzeug.security import generate_password_hash

from conftest import image_file, rows
from criticard import create_app
from criticard.db import get_db
from criticard.models import Card, User, Work
from criticard.security import session_identity
from criticard.validation import FormValidationError
from test_privacy import member


@pytest.fixture
def catalog_app(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'catalog-isolated-test-key',
        'DATABASE': str(tmp_path / 'catalog.db'), 'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
        'CAPA_FOLDER': str(tmp_path / 'covers'), 'ADM_USERNAME': '', 'ADM_SENHA': '',
        'ACCOUNT_MAIL_BACKEND': 'disabled', 'STORAGE_BACKEND': 'local',
        'ENVIRONMENT': 'development'})
    # The production factory registers this module; permit independent feature
    # tests while the application registration is being integrated.
    if 'admin_catalog' not in app.blueprints:
        from criticard.admin_catalog import bp
        app.register_blueprint(bp)
    with app.app_context():
        db = get_db()
        with db:
            for user_id, username in ((1, 'ALICE'), (2, 'BOB'), (3, 'ADMIN')):
                db.execute(insert(User).values(id=user_id, username=username, nome=username,
                    apelido='', about='', email=username.lower() + '@example.com',
                    senha=generate_password_hash('Password1!'), admin=int(user_id == 3)))
            db.execute(insert(Card).values(titulo='Histórico', capa='legacy.png',
                sobre='Crítica histórica', nota=80, author_id=1, obra_id=1))
    yield app
    app.extensions['database_engine'].dispose()


def administrator_data(app):
    with app.app_context():
        user = get_db().execute(select(User).where(User.id == 3)).fetchone()
        return {'usuario_id': 3, 'session_version': user['session_version'],
                'auth_stamp': session_identity(user)}


def test_work_model_supports_constrained_availability():
    assert hasattr(Work, 'active'), 'Catalog works need an availability field'


def test_shared_cover_contract_resolves_art_static_upload_and_rejects_untrusted_paths(catalog_app):
    from criticard.catalog_images import cover_metadata_for_work, default_cover_for_work
    with catalog_app.app_context():
        seeded = {'titulo': 'Elden Ring', 'category_slug': 'jogos', 'capa': None}
        assert default_cover_for_work(seeded) == 'catalog:jogos:0'
        assert cover_metadata_for_work(seeded)['cover_art']['marker'] == 'catalog:jogos:0'
        assert default_cover_for_work({**seeded, 'capa': 'default-avatar.svg'}) == 'catalog-static:default-avatar.svg'
        (Path(catalog_app.config['CAPA_FOLDER']) / 'custom.png').write_bytes(b'fixture')
        assert default_cover_for_work({**seeded, 'capa': 'custom.png'}) == 'custom.png'
        assert cover_metadata_for_work({**seeded, 'capa': 'custom.png'})['cover_url'] == '/media/cover/custom.png'
        for unsafe in ('../secret.png', 'https://host/cover.png', 'catalog:jogos:900', 'file.css'):
            assert default_cover_for_work({**seeded, 'capa': unsafe}) == 'default-cover.svg'


def test_retirement_hides_new_selections_and_preserves_existing_history(catalog_app):
    from criticard.admin_catalog.service import retire_work, restore_work
    from criticard.backlog.service import add_item, catalog_items, collection_items, update_item
    from criticard.catalog import get_catalog, selected_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        item, _ = add_item(1, {'obra_id': '1'})
        retire_work(3, credentials, 1)
        db = get_db()
        card = db.execute(select(Card).where(Card.obra_id == 1)).fetchone()
        assert card['titulo'] == 'Histórico' and card['capa'] == 'legacy.png'
        assert all(work['id'] != 1 for category in get_catalog() for work in category['works'])
        assert all(work['id'] != 1 for work in catalog_items(1, {'categoria': '', 'q': '', 'status': ''}))
        assert selected_work({'obra_id': '1'}, card)['active'] == 0
        with pytest.raises(FormValidationError):
            selected_work({'obra_id': '1'})
        with pytest.raises(NotFound):
            add_item(2, {'obra_id': '1'})
        assert collection_items(1, {'categoria': '', 'q': '', 'status': ''})[0]['work_id'] == 1
        assert update_item(1, item['id'], {'status': 'completed'})['status'] == 'completed'
        restore_work(3, credentials, 1)
        assert selected_work({'obra_id': '1'})['active'] == 1


def test_unused_retired_work_keeps_its_identifier(catalog_app):
    from criticard.admin_catalog.service import create_work, retire_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        retire_work(3, credentials, 30)
        new = create_work(3, credentials, {'titulo': 'Nova obra', 'categoria_id': '1'}, 'new.png')
        assert new['id'] > 30
        assert get_db().execute(select(Work.active).where(Work.id == 30)).scalar() == 0


def test_create_edit_preserve_generated_art_when_seed_title_changes(catalog_app):
    from criticard.admin_catalog.service import edit_work
    from criticard.catalog_images import default_cover_for_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        work = edit_work(3, credentials, 1, {'titulo': 'Título renomeado', 'categoria_id': '2'})
        assert work['capa'] == 'catalog:jogos:0'
        assert default_cover_for_work(work) == 'catalog:jogos:0'
        assert rows(catalog_app, 'SELECT titulo,capa FROM cards')[0] == {'titulo': 'Histórico', 'capa': 'legacy.png'}


@pytest.mark.parametrize('title', ['', '   ', 'x' * 121, 'nul\0title', '\ud800'])
def test_invalid_work_titles_are_rejected(catalog_app, title):
    from criticard.admin_catalog.service import create_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        with pytest.raises(FormValidationError) as rejected:
            create_work(3, credentials, {'titulo': title, 'categoria_id': '1'}, 'new.png')
        assert rejected.value.field == 'titulo'
    assert rows(catalog_app, 'SELECT COUNT(*) FROM obras')[0][0] == 30


@pytest.mark.parametrize('category', ['', 'bad', '-1', '9223372036854775808', '999'])
def test_invalid_categories_are_rejected(catalog_app, category):
    from criticard.admin_catalog.service import create_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        with pytest.raises(FormValidationError) as rejected:
            create_work(3, credentials, {'titulo': 'Nova obra', 'categoria_id': category}, 'new.png')
        assert rejected.value.field == 'categoria_id'


def test_casefold_duplicates_include_retired_work_and_allow_other_category(catalog_app):
    from criticard.admin_catalog.service import create_work, retire_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        retire_work(3, credentials, 1)
        with pytest.raises(FormValidationError) as duplicate:
            create_work(3, credentials, {'titulo': '  ELDEN RING  ', 'categoria_id': '1'}, 'new.png')
        assert 'reativ' in str(duplicate.value).lower()
        new = create_work(3, credentials, {'titulo': 'ELDEN RING', 'categoria_id': '2'}, 'new.png')
        assert new['categoria_id'] == 2


@pytest.mark.parametrize('changes', [{'admin': 0}, {'active': 0}, {'session_version': 1},
    {'senha': generate_password_hash('Changed2!')}])
@pytest.mark.parametrize('action', ['create', 'edit', 'delete', 'restore'])
def test_mutations_recheck_current_role_and_session(catalog_app, changes, action):
    from criticard.admin_catalog import service
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 3).values(**changes))
        with pytest.raises((Forbidden, service.CatalogSessionExpired)):
            if action == 'create':
                service.create_work(3, credentials, {'titulo': 'Novo', 'categoria_id': '1'}, 'new.png')
            elif action == 'edit':
                service.edit_work(3, credentials, 1, {'titulo': 'Alterado', 'categoria_id': '1'})
            elif action == 'delete':
                service.retire_work(3, credentials, 1)
            else:
                service.restore_work(3, credentials, 1)
    assert rows(catalog_app, 'SELECT titulo,active FROM obras WHERE id=1') == [{'titulo': 'Elden Ring', 'active': 1}]


@pytest.mark.parametrize('work_id', [0, -1, 2**63, 999999])
def test_administration_rejects_unknown_and_out_of_range_ids(catalog_app, work_id):
    from criticard.admin_catalog.service import get_work, retire_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        with pytest.raises(NotFound):
            get_work(work_id)
        with pytest.raises(NotFound):
            retire_work(3, credentials, work_id)


def test_replacing_cover_preserves_card_reference_and_cleans_unreferenced_file(catalog_app):
    from criticard.admin_catalog.service import edit_work
    from criticard.privacy.cleanup import cleanup_images
    credentials = administrator_data(catalog_app)
    folder = Path(catalog_app.config['CAPA_FOLDER'])
    (folder / 'shared.png').write_bytes(b'old shared cover')
    (folder / 'unused.png').write_bytes(b'old unused cover')
    with catalog_app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.id == 1).values(capa='shared.png'))
            db.execute(update(Card).where(Card.obra_id == 1).values(capa='shared.png'))
            db.execute(update(Work).where(Work.id == 2).values(capa='unused.png'))
        edit_work(3, credentials, 1, {'titulo': 'Elden Ring', 'categoria_id': '1'}, 'next.png')
        edit_work(3, credentials, 2, {'titulo': 'Hollow Knight', 'categoria_id': '1'}, 'next2.png')
        cleanup_images()
    assert (folder / 'shared.png').is_file()
    assert not (folder / 'unused.png').exists()


def test_cleanup_failure_remains_queued(catalog_app, monkeypatch):
    from criticard.admin_catalog.service import edit_work
    from criticard.privacy.cleanup import cleanup_images
    from criticard.storage import LocalStorage
    credentials = administrator_data(catalog_app)
    def unavailable(storage, filename):
        raise OSError('storage unavailable')
    monkeypatch.setattr(LocalStorage, 'remove', unavailable)
    with catalog_app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.id == 2).values(capa='pending.png'))
        edit_work(3, credentials, 2, {'titulo': 'Hollow Knight', 'categoria_id': '1'}, 'new.png')
        assert cleanup_images()['failed'] == 1
    assert rows(catalog_app, 'SELECT filename FROM pending_image_deletions') == [{'filename': 'pending.png'}]


def test_admin_pages_require_current_permission_and_mutations_require_csrf(catalog_app):
    guest = catalog_app.test_client()
    alice, alice_token = member(catalog_app, 1)
    admin, token = member(catalog_app, 3)
    for path in ('/admin/obras', '/admin/obras/nova', '/admin/obras/1/editar', '/admin/obras/1/excluir'):
        assert guest.get(path).status_code == 302
        assert alice.get(path).status_code == 403
        assert admin.get(path).status_code == 200
    assert admin.post('/admin/obras/1/excluir').status_code == 400
    assert alice.post('/admin/obras/1/excluir', data={'csrf_token': alice_token}).status_code == 403
    assert admin.post('/admin/obras/1/excluir', data={'csrf_token': token, 'confirm': '1'}).status_code == 302


def test_new_work_requires_cover_and_saves_uploaded_cover(catalog_app):
    admin, token = member(catalog_app, 3)
    data = {'titulo': 'Nova obra', 'categoria_id': '1', 'csrf_token': token}
    response = admin.post('/admin/obras/nova', data=data)
    assert response.status_code == 200 and 'capa-error' in response.text
    assert admin.post('/admin/obras/nova', data={**data, 'capa': image_file()}).status_code == 302
    work = rows(catalog_app, 'SELECT * FROM obras WHERE titulo=?', ('Nova obra',))[0]
    assert (Path(catalog_app.config['CAPA_FOLDER']) / work['capa']).is_file()


def test_role_revoked_during_upload_cannot_create_work_or_leave_unreferenced_file(catalog_app, monkeypatch):
    from criticard.admin_catalog import views
    admin, token = member(catalog_app, 3)
    original = views.save_image
    def revoke_after_upload(file, folder, required=False):
        filename = original(file, folder, required=required)
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 3).values(admin=0))
        return filename
    monkeypatch.setattr(views, 'save_image', revoke_after_upload)
    response = admin.post('/admin/obras/nova', data={'titulo': 'Não publicar', 'categoria_id': '1',
        'csrf_token': token, 'capa': image_file()})
    assert response.status_code == 403
    assert rows(catalog_app, 'SELECT COUNT(*) FROM obras')[0][0] == 30
    assert list(Path(catalog_app.config['CAPA_FOLDER']).iterdir()) == []


def test_admin_listing_filters_paginates_and_counts_usage(catalog_app):
    from criticard.admin_catalog.service import filters_from_args, list_works, retire_work
    credentials = administrator_data(catalog_app)
    with catalog_app.app_context():
        retire_work(3, credentials, 1)
        listing = list_works(filters_from_args({'status': 'archived', 'q': 'Elden', 'categoria': 'jogos'}))
        assert listing['total'] == 1
        work = listing['items'][0]
        assert work['title'] == 'Elden Ring' and work['card_count'] == 1 and work['backlog_count'] == 0
        assert work['cover_url'].startswith('/static/catalog/')
        assert list_works(filters_from_args({'status': 'all'}), page=2, per_page=10)['page'] == 2


def test_admin_mutations_use_persistent_budget(catalog_app):
    catalog_app.config['SETTINGS_SECURITY_ATTEMPT_LIMIT'] = 1
    admin, token = member(catalog_app, 3)
    assert admin.post('/admin/obras/1/excluir', data={'csrf_token': token, 'confirm': '1'}).status_code == 302
    response = admin.post('/admin/obras/1/reativar', data={'csrf_token': token})
    assert response.status_code == 429 and int(response.headers['Retry-After']) > 0


@pytest.fixture
def catalog_remote_storage(catalog_app, monkeypatch):
    from criticard import storage
    from test_storage import FakeS3
    fake = FakeS3()
    monkeypatch.setattr(storage, '_client', lambda settings: fake)
    catalog_app.config.update(STORAGE_BACKEND='s3', S3_BUCKET='test-public-images',
        S3_ACCESS_KEY_ID='test-only-key', S3_SECRET_ACCESS_KEY='test-only-secret',
        S3_PUBLIC_BASE_URL='https://cdn.example.test/images', S3_PREFIX='criticard')
    return fake


@pytest.mark.parametrize('backend', ['local', 's3'])
def test_administrative_cover_is_displayed_in_catalog_and_collections(
        catalog_app, catalog_remote_storage, backend):
    from criticard.backlog.service import add_item
    catalog_app.config['STORAGE_BACKEND'] = backend
    admin, token = member(catalog_app, 3)
    response = admin.post('/admin/obras/nova', data={'titulo': 'Nova imagem',
        'categoria_id': '1', 'csrf_token': token, 'capa': image_file()})
    assert response.status_code == 302
    work = rows(catalog_app, "SELECT * FROM obras WHERE titulo='Nova imagem'")[0]
    expected = ('/media/cover/' if backend == 'local' else
        'https://cdn.example.test/images/criticard/covers/') + work['capa']
    guest = catalog_app.test_client()
    assert expected in guest.get('/catalogo?q=Nova+imagem').text
    with catalog_app.app_context():
        add_item(1, {'obra_id': str(work['id']), 'visibility': 'public'})
    alice, _ = member(catalog_app, 1)
    assert expected in alice.get('/backlog?q=Nova+imagem').text
    assert expected in guest.get('/colecao/ALICE?q=Nova+imagem').text
    if backend == 's3':
        assert ('test-public-images', 'criticard/covers/' + work['capa']) in catalog_remote_storage.objects
        assert list(Path(catalog_app.config['CAPA_FOLDER']).iterdir()) == []


def test_failed_duplicate_upload_discards_only_new_remote_object(catalog_app, catalog_remote_storage):
    admin, token = member(catalog_app, 3)
    data = {'titulo': 'Nova imagem', 'categoria_id': '1', 'csrf_token': token}
    assert admin.post('/admin/obras/nova', data={**data, 'capa': image_file()}).status_code == 302
    original_objects = dict(catalog_remote_storage.objects)
    rejected = admin.post('/admin/obras/nova', data={**data, 'titulo': 'NOVA IMAGEM', 'capa': image_file()})
    assert rejected.status_code == 200 and 'titulo-error' in rejected.text
    assert catalog_remote_storage.objects == original_objects
    assert rows(catalog_app, 'SELECT COUNT(*) FROM obras')[0][0] == 31
    assert rows(catalog_app, 'SELECT COUNT(*) FROM pending_image_deletions')[0][0] == 0
