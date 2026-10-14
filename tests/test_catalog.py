import re

from criticard import create_app
from conftest import image_file, post, rows


def test_catalog_has_six_categories_and_five_works_each(app):
    categories = rows(app, "SELECT c.nome,COUNT(o.id) FROM categorias c JOIN obras o ON o.categoria_id=c.id GROUP BY c.id")
    assert len(categories) == 6
    assert all(row[1] >= 5 for row in categories)


def test_publication_requires_known_work(alice, app):
    for work in ("", "999999", "invalid", "9223372036854775808", "-9223372036854775809"):
        response = post(alice, "/cadastro_cards", {"obra_id": work, "titulo": "Livre", "sobre": "Crítica", "nota": "90", "capa": image_file()})
        assert response.status_code == 200 and 'id="obra_id-error"' in response.text
    assert rows(app, "SELECT COUNT(*) FROM cards")[0][0] == 1


def test_server_uses_canonical_title_and_validates_category(alice, app):
    work = rows(app, "SELECT id,titulo,categoria_id FROM obras WHERE titulo='Berserk'")[0]
    payload = {"obra_id": str(work["id"]), "categoria_id": str(work["categoria_id"]), "titulo": "Título forjado", "sobre": "Crítica", "nota": "100", "capa": image_file()}
    assert post(alice, "/cadastro_cards", payload).status_code == 302
    card = rows(app, "SELECT * FROM cards WHERE id=2")[0]
    assert card["titulo"] == "Berserk" and card["obra_id"] == work["id"]
    payload.update(categoria_id="1", capa=image_file())
    assert post(alice, "/cadastro_cards", payload).status_code == 200
    assert rows(app, "SELECT COUNT(*) FROM cards")[0][0] == 2


def test_catalog_setup_is_repeatable_and_preserves_legacy_cards(app):
    for _ in range(2):
        create_app(dict(app.config))
    assert rows(app, "SELECT COUNT(*) FROM obras")[0][0] == 30
    card = rows(app, "SELECT * FROM cards WHERE id=1")[0]
    assert card["titulo"] == "Card da Alice" and card["obra_id"] is None


def test_legacy_title_remains_editable_without_catalog_selection(alice):
    response = alice.get('/editar_card/1')
    control = re.search(r'<input id="titulo"[^>]*>', response.text).group(0)
    assert "readonly" not in control
