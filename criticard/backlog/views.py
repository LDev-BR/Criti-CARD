"""HTML pages and CSRF-protected collection mutations."""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import NotFound

from criticard.catalog_images import cover_metadata_for_work
from criticard.card_reviews import reviewed_works
from criticard.security import login_required
from criticard.progression.types import ProgressionError
from . import service

bp = Blueprint("backlog", __name__)


@bp.errorhandler(ProgressionError)
def account_error(error):
    if _wants_json():
        return jsonify(error=str(error),field=error.field),error.status
    return render_template('error.html',code=error.status,message=str(error)),error.status


def _wants_json():
    return request.is_json or request.accept_mimetypes.best == "application/json"


def _data():
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise service.BacklogValidationError("form", "Envie os dados da obra em um objeto JSON.")
        return data
    return request.form


def _decorate(items):
    reviews = reviewed_works(g.user['id']) if g.user else {}
    for item in items:
        item.update(cover_metadata_for_work(item))
        item['review_card_id'] = reviews.get(item.get('work_id', item['id']))
        if "status" in item:
            item["status_label"] = service.status_label(item["status"], item["category_slug"])
    return items


def _context(filters):
    return {"filters": filters, "categories": service.categories(), "statuses": service.STATUSES,
            "units": service.UNITS, "status_label": service.status_label}


def _render_collection(owner, own_collection, *, own_route=False):
    from criticard.settings.service import get_preferences
    filters = service.filters_from_args(request.args)
    items = _decorate(service.collection_items(owner["id"], filters, public_only=not own_collection))
    counts = service.status_counts(owner["id"], public_only=not own_collection)
    endpoint = "backlog.index" if own_route else "backlog.collection"
    route_args = {} if own_route else {"username": owner["username"]}
    return render_template("backlog/index.html", items=items, owner=owner, own_collection=own_collection,
                           counts=counts, collection_total=sum(counts.values()),
                           collection_endpoint=endpoint, collection_route_args=route_args,
                           default_visibility=get_preferences(owner["id"])["backlog_visibility"] if own_collection else None,
                           **_context(filters))


@bp.get("/backlog")
@login_required
def index():
    return _render_collection(g.user, True, own_route=True)


@bp.get("/colecao/<username>")
def collection(username):
    owner = service.collection_owner(username)
    own_collection = g.user is not None and g.user["id"] == owner["id"]
    return _render_collection(owner, own_collection)


@bp.get("/catalogo")
def catalog():
    filters = service.filters_from_args(request.args)
    user_id = g.user["id"] if g.user else None
    works = _decorate(service.catalog_items(user_id, filters))
    from criticard.social import service as social
    work_follows = social.work_follow_states([work['id'] for work in works], user_id)
    categories = service.categories()
    category_follows = social.category_follow_states([category['id'] for category in categories], user_id)
    for work in works:
        work['followed'] = work_follows[work['id']]
    return render_template("backlog/catalog.html", works=works,
        work_follows=work_follows, category_follows=category_follows,
        **_context(filters))


def _failure(error):
    if _wants_json():
        status = 404 if isinstance(error, NotFound) else 422
        return jsonify(error="Item não encontrado." if status == 404 else str(error),
                       field=getattr(error, "field", None)), status
    if isinstance(error, NotFound):
        raise error
    flash(str(error), "error")
    return redirect(url_for("backlog.index"))


def _serialized(item):
    return {name: item[name] for name in ("id", "work_id", "status", "visibility", "progress", "progress_unit")}


@bp.post("/backlog/add")
@login_required
def add_item():
    try:
        item, created = service.add_item(g.user["id"], _data())
    except (service.BacklogValidationError, NotFound) as error:
        return _failure(error)
    if _wants_json():
        return jsonify(item=_serialized(item), created=created,
                       message="Obra adicionada à sua coleção." if created else "Esta obra já está na sua coleção."), 201 if created else 200
    flash("Obra adicionada à sua coleção." if created else "Esta obra já está na sua coleção.", "success")
    return redirect(url_for("backlog.index"))


@bp.post("/backlog/<int:item_id>/update")
@login_required
def update_item(item_id):
    try:
        item = service.update_item(g.user["id"], item_id, _data())
    except (service.BacklogValidationError, NotFound) as error:
        return _failure(error)
    if _wants_json():
        return jsonify(item=_serialized(item), message="Coleção atualizada.")
    flash("Coleção atualizada.", "success")
    return redirect(url_for("backlog.index"))


@bp.post("/backlog/<int:item_id>/remove")
@login_required
def remove_item(item_id):
    try:
        service.remove_item(g.user["id"], item_id)
    except NotFound as error:
        return _failure(error)
    if _wants_json():
        return jsonify(removed=True, message="Obra removida da sua coleção.")
    flash("Obra removida da sua coleção.", "success")
    return redirect(url_for("backlog.index"))
