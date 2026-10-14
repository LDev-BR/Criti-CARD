import pytest

from conftest import post, rows
from criticard.db import get_db


def add_card(app, title, author=2):
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO cards (titulo,capa,sobre,nota,author_id) VALUES (?,?,?,?,?)",
                       (title, "legacy.png", "Uma critica publica", 85, author))


def test_discovery_hub_and_critique_feed_have_separate_routes(client):
    hub = client.get("/feed")
    critique_feed = client.get("/criticas")
    assert hub.status_code == critique_feed.status_code == 200
    assert "O que vale descobrir hoje?" in hub.text
    assert 'href="/criticas"' in hub.text
    assert "Card da Alice" in critique_feed.text


def test_feed_is_public_and_shows_cards_from_other_users(client, app):
    add_card(app, "Card do Bob")
    response = client.get("/criticas")
    assert response.status_code == 200
    assert "Card da Alice" in response.text
    assert "Card do Bob" in response.text
    assert '/perfil/ALICE' in response.text
    assert "alice@example.com" not in response.text


def test_feed_displays_newest_card_first(client, app):
    add_card(app, "Novo card")
    text = client.get("/criticas").text
    assert "Novo card" in text and "Card da Alice" in text
    assert text.index("Novo card") < text.index("Card da Alice")


@pytest.mark.parametrize("query", ["Alice", "historia inexistente", "' OR 1=1 --"])
def test_feed_search_does_not_ignore_query(client, query):
    response = client.get("/criticas", query_string={"q": query})
    assert response.status_code == 200
    assert ("Card da Alice" in response.text) == (query == "Alice")


def test_feed_search_by_title(client, app):
    add_card(app, "Baldur's Gate 3")
    response = client.get("/criticas", query_string={"q": "Baldur"})
    assert "Baldur&#39;s Gate 3" in response.text
    assert "Card da Alice" not in response.text


def test_search_wildcards_are_literal(client, app):
    add_card(app, "100% aventura")
    response = client.get("/criticas", query_string={"q": "%"})
    assert response.status_code == 200
    assert "100% aventura" in response.text
    assert "Card da Alice" not in response.text


def test_feed_is_paginated_without_losing_cards(client, app):
    for number in range(1, 14):
        add_card(app, f"Review {number:02}")
    first = client.get("/criticas")
    second = client.get("/criticas?page=2")
    assert first.status_code == second.status_code == 200
    assert "Review 13" in first.text and "Review 02" in first.text
    assert "Review 01" not in first.text and "Card da Alice" not in first.text
    assert "Review 01" in second.text and "Card da Alice" in second.text
    assert "Review 02" not in second.text


@pytest.mark.parametrize("page", ["oops", "-1", "0"])
def test_invalid_page_returns_first_page(client, page):
    response = client.get("/criticas", query_string={"page": page})
    assert response.status_code == 200
    assert "Card da Alice" in response.text


def test_page_beyond_last_returns_404(client):
    assert client.get("/criticas?page=99999999999999999999999999").status_code == 404


def test_public_profile_hides_private_data_and_other_users_cards(client, app):
    add_card(app, "Card do Bob")
    response = client.get("/perfil/alice")
    assert response.status_code == 200
    assert "Minha bio" in response.text and "Card da Alice" in response.text
    assert "Card do Bob" not in response.text
    assert "alice@example.com" not in response.text
    password_hash = rows(app, "SELECT senha FROM usuarios WHERE id=1")[0][0]
    assert password_hash not in response.text
    assert "Editar perfil" not in response.text
    assert "Excluir card" not in response.text


def test_unknown_profile_returns_404(client):
    assert client.get("/perfil/missing").status_code == 404


def test_authenticated_feed_exposes_management_only_for_author(alice, app):
    add_card(app, "Card do Bob")
    response = alice.get("/criticas")
    assert response.status_code == 200
    assert '/deletar_card/1' in response.text
    assert '/deletar_card/2' not in response.text


def test_profile_pagination_contains_only_its_author(client, app):
    for number in range(1, 14):
        add_card(app, f"Alice review {number:02}", author=1)
    add_card(app, "Card do Bob")
    response = client.get("/perfil/ALICE?page=2")
    assert response.status_code == 200
    assert "Alice review 01" in response.text
    assert "Card da Alice" in response.text
    assert "Card do Bob" not in response.text


@pytest.mark.parametrize("query", ["séries", "ficção", "LUÍS"])
def test_search_handles_unicode_case_for_legacy_titles_and_authors(client, app, query):
    add_card(app, "SÉRIES DE FICÇÃO")
    with app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE usuarios SET nome='Luís' WHERE id=2")
    response = client.get("/criticas", query_string={"q": query})
    assert response.status_code == 200
    assert "SÉRIES DE FICÇÃO" in response.text
