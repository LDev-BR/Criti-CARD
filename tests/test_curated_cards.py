"""Authors review catalog works; cover curation remains administrative."""
from pathlib import Path

from criticard.db import get_db
from conftest import image_file, post, rows


def publish(client, **extra):
    return post(client, '/cadastro_cards', dict(obra_id='1', sobre='Uma jornada inesquecível.', nota='90', **extra))


def test_author_upload_cannot_override_curated_cover(alice, app):
    assert publish(alice, capa=image_file()).status_code == 302
    assert rows(app, 'SELECT capa FROM cards WHERE id=2')[0][0] == 'catalog:jogos:0'
    assert list(Path(app.config['CAPA_FOLDER']).iterdir()) == []


def test_catalog_cover_and_title_updates_appear_without_rewriting_old_reviews(alice, app):
    assert publish(alice).status_code == 302
    with app.app_context():
        with get_db() as db:
            db.execute("UPDATE obras SET titulo=?,search_title=?,capa=? WHERE id=1",
                ('Título atualizado', 'título atualizado', 'catalog:jogos:1'))
    page = alice.get('/card/2').text
    assert 'Título atualizado' in page and 'catalog-art--col-1' in page
    assert 'Título atualizado' in alice.get('/criticas?q=Título+atualizado').text
    card = rows(app, 'SELECT titulo,capa FROM cards WHERE id=2')[0]
    assert card['titulo'] == 'Elden Ring' and card['capa'] == 'catalog:jogos:0'


def test_retired_work_rejects_new_card_but_existing_review_remains_editable(alice, app):
    assert publish(alice).status_code == 302
    with app.app_context():
        with get_db() as db: db.execute('UPDATE obras SET active=0 WHERE id=1')
    response = publish(alice)
    assert response.status_code == 200 and 'obra_id-error' in response.text
    assert post(alice, '/editar_card/2', {'obra_id':'1', 'sobre':'Texto revisado', 'nota':'85'}).status_code == 302
    assert rows(app, 'SELECT sobre FROM cards WHERE id=2')[0][0] == 'Texto revisado'
    assert rows(app, 'SELECT COUNT(*) FROM cards')[0][0] == 2
    assert '(retirada do catálogo)' in alice.get('/editar_card/2').text


def test_work_retired_after_validation_cannot_be_published(alice, app, monkeypatch):
    from criticard import cards
    original = cards._lock_author
    def retire_before_author_lock(db):
        with app.app_context():
            with get_db() as other:
                other.execute('UPDATE obras SET active=0 WHERE id=1')
        original(db)
    monkeypatch.setattr(cards, '_lock_author', retire_before_author_lock)
    response = publish(alice)
    assert response.status_code == 200 and 'obra_id-error' in response.text
    assert 'Uma jornada inesquecível.' in response.text
    assert rows(app, 'SELECT COUNT(*) FROM cards')[0][0] == 1


def test_legacy_review_keeps_its_existing_cover_when_edited(alice, app):
    old = Path(app.config['CAPA_FOLDER']) / 'legacy.png'
    old.write_bytes(b'previous cover fixture')
    assert post(alice, '/editar_card/1', {'titulo':'Crítica antiga', 'sobre':'Revisada', 'nota':'80',
        'capa':image_file()}).status_code == 302
    assert rows(app, 'SELECT capa FROM cards WHERE id=1')[0][0] == 'legacy.png'
    assert old.is_file() and len(list(old.parent.iterdir())) == 1
