"""Original local artwork mapping, safe covers, and honest collection copy."""
from pathlib import Path
from html import unescape
import re
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image
from sqlalchemy import select, update

from criticard.catalog import get_catalog, selected_work
from criticard.catalog_images import art_for_marker, art_for_work
from criticard.db import get_db
from criticard.models import Work
from criticard.settings.service import save_preferences
from conftest import post, rows


def test_each_of_the_thirty_seed_works_has_a_distinct_local_illustration(app):
    with app.app_context():
        categories = get_catalog()
        works = [work for category in categories for work in category['works']]
        arts = [work['cover_art'] for work in works]
        assert len(works) == 30 and all(arts)
        assert len({art['marker'] for art in arts}) == 30
        assert len({art['filename'] for art in arts}) == 6
        for art in arts:
            assert art['columns'] == 3 and art['rows'] == 2
            assert 0 <= art['column'] < 3 and 0 <= art['row'] < 2
            assert art['filename'].startswith('catalog/')
            assert 'Ilustração temática' in art['label']
            with Image.open(Path(app.static_folder) / art['filename']) as image:
                assert image.format == 'PNG'
                assert image.width >= 1500 and image.height >= 800
                assert image.width / image.height == pytest.approx(2.25, abs=.01)
                image.verify()


def test_selected_work_includes_category_and_same_illustration_as_catalog(app):
    with app.app_context():
        work = get_db().execute(select(Work).where(Work.titulo == 'Duna')).fetchone()
        selection = selected_work({'obra_id': str(work['id'])})
        assert selection['category_slug'] == 'livros'
        assert selection['cover_art'] == art_for_work(selection)
        assert selection['cover_art']['marker'] == 'catalog:livros:1'


@pytest.mark.parametrize('marker', [
    None, '', [], {}, 'catalog:jogos:5', 'catalog:jogos:-1', 'catalog:jogos:01',
    'catalog:livros:999', 'catalog:unknown:0', 'catalog:../uploads:0',
    '../../private.png', 'catalog/jogos-atlas.png', 'https://example.com/cover.png',
])
def test_unknown_markers_never_resolve_to_paths(marker):
    assert art_for_marker(marker) is None


def test_artwork_mapping_does_not_share_mutable_metadata_between_callers():
    first = art_for_marker('catalog:jogos:0')
    first['filename'] = 'https://example.com/untrusted.png'
    assert art_for_marker('catalog:jogos:0')['filename'] == 'catalog/jogos-atlas.png'


def test_mapping_uses_title_and_category_instead_of_database_id():
    assert art_for_work({'id': 9000, 'titulo': 'Hades', 'category_slug': 'jogos'})['marker'] == 'catalog:jogos:3'
    assert art_for_work({'id': 4, 'titulo': 'Hades', 'category_slug': 'filmes'}) is None
    assert art_for_work({'titulo': 'Uma obra futura', 'category_slug': 'jogos'}) is None


def test_custom_cover_takes_priority_over_generated_artwork(app, client):
    asset = Path(app.static_folder) / 'default-avatar.svg'
    # Existing local images remain valid even when the work has original artwork.
    assert asset.is_file()
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.titulo == 'Hades').values(capa='default-avatar.svg'))
        assert art_for_work({'titulo': 'Hades', 'category_slug': 'jogos', 'capa': 'default-avatar.svg'}) is None
    page = client.get('/catalogo?categoria=jogos&q=Hades')
    assert page.status_code == 200
    assert '<img src="/static/default-avatar.svg"' in page.text
    assert 'data-catalog-art=' not in page.text


def test_public_catalog_shows_thirty_local_tiles_and_no_external_images(client):
    response = client.get('/catalogo')
    assert response.status_code == 200
    assert response.text.count('data-catalog-art=') == 30
    assert response.text.count('Ilustração temática original') == 30
    images = re.findall(r'<img[^>]+src="([^"]+)"', response.text)
    assert images and all(not src.startswith(('http:', 'https:', '//')) for src in images)
    assert not re.search(r'\sstyle=', response.text)


def test_guest_login_keeps_catalog_category_and_search(client):
    page = client.get('/catalogo?categoria=mangas&q=Berserk')
    hrefs = re.findall(r'href="([^"]+)"', page.text)
    destinations = [parse_qs(urlparse(unescape(href)).query).get('next', [''])[0] for href in hrefs]
    catalog_destinations = [urlparse(destination) for destination in destinations if urlparse(destination).path == '/catalogo']
    assert any(parse_qs(destination.query) == {'categoria': ['mangas'], 'q': ['Berserk']} for destination in catalog_destinations)


@pytest.mark.parametrize('cover', ['https://example.com/cover.png', '../outside.png', 'backlog.css', 'catalog:livros:100'])
def test_invalid_work_cover_uses_safe_default(client, app, cover):
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.titulo == 'Duna').values(capa=cover))
    response = client.get('/catalogo?categoria=livros&q=Duna')
    assert '<img src="/static/default-cover.svg"' in response.text
    assert 'data-catalog-art=' not in response.text
    assert cover not in re.findall(r'<img[^>]+src="([^"]+)"', response.text)


def test_missing_original_asset_uses_safe_default_without_broken_url(client, app, tmp_path):
    assets = tmp_path / 'missing-art-assets'
    assets.mkdir()
    app.static_folder = str(assets)
    response = client.get('/catalogo?categoria=livros&q=Duna')
    assert '<img src="/static/default-cover.svg"' in response.text
    assert '/static/catalog/livros-atlas.png' not in response.text


@pytest.mark.parametrize('visibility,copy', [('private', 'Novas obras começam privadas'), ('public', 'Novas obras começam públicas')])
def test_collection_copy_and_added_item_follow_saved_visibility(alice, app, visibility, copy):
    with app.app_context():
        save_preferences(1, 'privacidade', {'backlog_visibility': visibility})
        work_id = get_db().execute(select(Work.id).where(Work.titulo == 'Duna')).scalar()
    assert post(alice, '/backlog/add', {'obra_id': str(work_id)}).status_code == 302
    page = alice.get('/backlog')
    assert copy in page.text
    assert 'Cada obra começa privada' not in page.text
    assert rows(app, 'SELECT visibility FROM backlog_items WHERE work_id=?', (work_id,))[0]['visibility'] == visibility
