from urllib.parse import parse_qs, urlsplit
import re

from criticard.db import get_db


def add_review(app, work, score, text="Uma boa história", author_id=2):
    with app.app_context():
        db = get_db()
        entry = db.execute("SELECT id,titulo FROM obras WHERE titulo=?", (work,)).fetchone()
        with db:
            db.execute("INSERT INTO cards (titulo,capa,sobre,nota,author_id,obra_id) VALUES (?,?,?,?,?,?)",
                       (entry["titulo"], "legacy.png", text, score, author_id, entry["id"]))
        return entry["id"]


def add_reviewer(app, index):
    with app.app_context():
        with get_db() as db:
            return db.execute(
                "INSERT INTO usuarios (username,nome,apelido,about,email,senha) "
                "VALUES (?,?,?,?,?,?) RETURNING id",
                (f"BOB_READER_{index}", f"Bob {index}", "Leitor", "",
                 f"bob-reader-{index}@example.test", "unused-fixture-hash"),
            ).scalar()


def test_category_work_and_score_filters_combine_with_search(client, app):
    work = add_review(app, "Berserk", 100)
    add_review(app, "Berserk", 75, author_id=add_reviewer(app, 1))
    add_review(app, "Elden Ring", 99)
    response = client.get('/criticas', query_string={'categoria':'mangas','obra':str(work),'nota_min':'90','q':'Bob'})
    assert response.status_code == 200
    assert response.text.count('data-review-card') == 1
    assert 'data-score="100"' in response.text
    assert 'data-score="75"' not in response.text and 'Elden Ring</h2>' not in response.text


def test_sort_uses_score_and_stable_card_order(client, app):
    add_review(app, "Berserk", 20)
    add_review(app, "Duna", 100)
    add_review(app, "Hades", 100)
    highest = client.get('/criticas?ordem=highest').text
    lowest = client.get('/criticas?ordem=lowest').text
    assert highest.index('data-title="Hades"') < highest.index('data-title="Duna"') < highest.index('data-title="Berserk"')
    assert lowest.index('data-title="Berserk"') < lowest.index('data-title="Duna"')


def test_pagination_retains_all_active_filters(client, app):
    work = None
    for index in range(14):
        work = add_review(app, "Berserk", 90, author_id=add_reviewer(app, index))
    response = client.get('/criticas', query_string={'categoria':'mangas','obra':str(work),'nota_min':'80','ordem':'highest','q':'Berserk'})
    assert response.status_code == 200 and response.text.count('data-review-card') == 12
    # Match the actual pagination link even when it contains decorative SVGs.
    pagination = response.text.split('aria-label="Paginação"')[-1]
    href = re.search(r'href="([^"]+)"', pagination).group(1).replace('&amp;', '&')
    args = parse_qs(urlsplit(href).query)
    assert args == {'q':['Berserk'],'categoria':['mangas'],'obra':[str(work)],'nota_min':['80'],'ordem':['highest'],'page':['2']}
    second = client.get(href)
    assert second.status_code == 200 and second.text.count('data-review-card') == 2


def test_invalid_filters_cannot_cause_sql_errors_or_change_query(client):
    response = client.get('/criticas', query_string={'categoria':"' OR 1=1 --",'obra':str(2**100),'nota_min':'oops','ordem':'nota; DROP TABLE cards'})
    assert response.status_code == 200
    assert 'data-title="Card da Alice"' in response.text
    assert 'value="recent" selected' in response.text


def test_footer_category_link_filters_the_community(client, app):
    add_review(app, "Berserk", 95)
    add_review(app, "Duna", 80)
    response = client.get('/criticas?categoria=mangas')
    assert 'data-title="Berserk"' in response.text
    assert 'data-title="Duna"' not in response.text
    assert 'id="community-filters"' in response.text
