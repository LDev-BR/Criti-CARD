"""Card publication and author-owned deletion."""
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from .db import get_db
from .catalog import get_catalog, selected_work
from .catalog_images import art_for_marker, default_cover_for_work
from .storage import image_url
from .queries import get_card
from .security import login_required, valid_session_identity
from .validation import validate_card
from .models import Card, User, Work, utcnow
from .card_reviews import DuplicateReview, existing_review, require_unique_review, reviewed_works
from .progression.service import record_action, claim_notice
from .progression.presentation import announce

bp = Blueprint("cards", __name__)


def _lock_author(db):
    author = db.execute(update(User).where(User.id == g.user['id'], User.active == 1)
                        .values(session_version=User.session_version).returning(*User.__table__.columns)).fetchone()
    if not valid_session_identity(author, session):
        session.clear()
        g.user = None
        abort(401)


def _lock_selected_work(db, form, previous):
    work = selected_work(form, previous)
    if work is not None:
        # A retirement or cover edit that committed during form validation must
        # be visible before publication. Hold the work until the card commits.
        db.execute(update(Work).where(Work.id == work['id']).values(active=Work.active))
        work = selected_work(form, previous)
    return work


@bp.route("/cadastro_cards", methods=["GET", "POST"])
@bp.route("/editar_card/<int:id>", methods=["GET", "POST"], endpoint="edit_card")
@login_required
def cadastro_cards(id=None):
    card = get_card(id) if id is not None else None
    if card is not None and card["author_id"] != g.user["id"]:
        abort(403)
    if card is not None and card['archived']:
        flash('Esta crítica faz parte do seu histórico privado. Edite o card publicado para reavaliar a obra.', 'info')
        return redirect(url_for('cards.detail', id=id))
    values = dict(request.form) if request.method == "POST" else (dict(card) if card else {})
    if request.method == 'GET' and card is None and request.args.get('obra_id'):
        try:
            requested_work = int(request.args['obra_id'])
            if not 1 <= requested_work <= 2**63 - 1:
                raise ValueError('Invalid selected work')
            existing = existing_review(g.user['id'], requested_work)
            if existing is not None:
                flash('Você já avaliou esta obra. Atualize seu card existente.', 'info')
                return redirect(url_for('cards.edit_card', id=existing))
            work = selected_work(request.args)
            values.update(titulo=work['titulo'],obra_id=work['id'],categoria_id=work['categoria_id'])
        except ValueError:
            pass
    field_errors = {}
    duplicate_card_id = None
    if request.method == "POST":
        try:
            work = selected_work(request.form, card)
            if work:
                values.update(titulo=work["titulo"], obra_id=work["id"], categoria_id=work["categoria_id"])
            title, description, score = validate_card(values)
            db = get_db()
            previous = None
            notice = None
            with db:
                _lock_author(db)
                if card is not None:
                    previous = db.execute(update(Card).where(Card.id == id, Card.author_id == g.user['id'])
                        .values(updated_at=Card.updated_at).returning(*Card.__table__.columns)).fetchone()
                    if previous is None:
                        abort(404)
                work = _lock_selected_work(db, request.form, previous)
                if work:
                    require_unique_review(g.user['id'], work['id'], excluding=id)
                title = work['titulo'] if work else title
                cover = default_cover_for_work(work) if work else previous['capa']
                if card is None:
                    new_id = db.execute(insert(Card).values(titulo=title,capa=cover,sobre=description,nota=score,
                               author_id=g.user['id'],obra_id=work['id'] if work else None,search_title=title.casefold())
                               .returning(Card.id)).scalar()
                    if work:
                        record_action(db,g.user['id'],'card_published',utcnow(),work_id=work['id'],category_id=work['categoria_id'])
                else:
                    db.execute(update(Card).where(Card.id == id,Card.author_id == g.user['id']).values(
                               titulo=title,capa=cover,sobre=description,nota=score,
                               obra_id=work['id'] if work else None,search_title=title.casefold(),updated_at=utcnow()))
                    if previous['capa'] != cover:
                        from .privacy.cleanup import queue_image
                        queue_image('cover', previous['capa'])
                    if any(previous[field]!=value for field,value in (
                        ('titulo',title),('capa',cover),('sobre',description),('nota',score),('obra_id',work['id'] if work else None))):
                        record_action(db,g.user['id'],'activity',utcnow())
                notice = claim_notice(db,g.user['id'],utcnow())
            if card is not None and previous['capa'] != cover:
                from .privacy.cleanup import cleanup_images
                if cleanup_images()['failed']:
                    flash('A imagem anterior tem remoção pendente no armazenamento. A equipe precisa concluir a limpeza.', 'info')
            flash("Card atualizado." if card else "Card publicado!", "success")
            announce(notice)
            return redirect(url_for("profiles.dashboard"))
        except ValueError as error:
            field_errors[getattr(error, "field", "obra_id")] = str(error)
            duplicate_card_id = getattr(error, 'card_id', None)
        except IntegrityError:
            # The index is the final guard, including writes outside this route.
            duplicate_card_id = existing_review(g.user['id'], work['id'], excluding=id) if work else None
            if duplicate_card_id is None:
                raise
            field_errors['obra_id'] = str(DuplicateReview(duplicate_card_id))
    catalog = get_catalog()
    if card and card['obra_id']:
        existing_work = selected_work({}, card)
        if existing_work['active'] != 1:
            existing_work['option_label'] = existing_work['titulo'] + ' (retirada do catálogo)'
            next(category for category in catalog if category['id'] == existing_work['categoria_id'])['works'].append(existing_work)
    preview = next((work for category in catalog for work in category['works']
                    if str(work['id']) == str(values.get('obra_id', ''))), None)
    preview_art = preview['cover_art'] if preview else art_for_marker(card['capa']) if card else None
    preview_cover_source = preview['cover_url'] if preview else image_url('cover', card['capa'] if card else 'default-cover.svg')
    existing_cards = reviewed_works(g.user['id'], excluding=id)
    for category in catalog:
        for work in category['works']:
            work['cover_source'] = work['cover_url']
            work['existing_card_id'] = existing_cards.get(work['id'])
    from .progression.queries import journey_summary, public_styles
    return render_template("cadastro_cards.html", values=values, editing=card is not None,
                           progression_style=public_styles([g.user['id']])[g.user['id']],progression_summary=journey_summary(g.user['id']),
                           card=card, field_errors=field_errors, catalog=catalog, preview_art=preview_art,
                           preview_cover_source=preview_cover_source, duplicate_card_id=duplicate_card_id)


@bp.get("/card/<int:id>")
def detail(id):
    from .social.service import SocialError, card_social_state, comments_for_card
    card = get_card(id)
    try:
        comments = comments_for_card(id, request.args.get('comments_page', 1, type=int) or 1,
            archived_owner_id=g.user['id'] if g.user else None)
    except SocialError as error:
        abort(error.status, description=str(error))
    return render_template("card_detail.html", c=card, card_comments=comments,
                           social_state=card_social_state([id],g.user['id'] if g.user else None)[id])


@bp.post("/deletar_card/<int:id>")
@login_required
def deletar_card(id):
    db = get_db()
    if not 1 <= id <= 2**63-1:
        abort(404)
    card = db.execute(select(Card).where(Card.id == id)).fetchone()
    if card is None:
        abort(404)
    if card["author_id"] != g.user["id"]:
        abort(403)
    with db:
        _lock_author(db)
        card = db.execute(update(Card).where(Card.id == id, Card.author_id == g.user['id'])
            .values(updated_at=Card.updated_at).returning(*Card.__table__.columns)).fetchone()
        if card is None:
            abort(404)
        db.execute(delete(Card).where(Card.id == id,Card.author_id == g.user['id']))
        from .privacy.cleanup import queue_image
        queue_image('cover', card['capa'])
    from .privacy.cleanup import cleanup_images
    if cleanup_images()['failed']:
        flash('A capa tem remoção pendente no armazenamento. A equipe precisa concluir a limpeza.', 'info')
    flash("Card excluído.", "success")
    return redirect(url_for("profiles.dashboard"))
