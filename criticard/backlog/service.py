"""Portable queries and ownership rules for collections."""
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from werkzeug.exceptions import NotFound

from criticard.db import get_db
from criticard.models import Category, User, Work, utcnow
from criticard.validation import storable_text
from .models import BacklogItem
from ..progression.service import lock_owner, record_action, require_owner_session

STATUSES = {
    "planned": "Quero consumir", "in_progress": "Em andamento", "completed": "Concluído",
    "paused": "Pausado", "dropped": "Abandonado",
}
UNITS = {"hours": "horas", "episodes": "episódios", "chapters": "capítulos"}
VERBS = {
    "jogos": ("Quero jogar", "Jogando", "Jogado"),
    "filmes": ("Quero assistir", "Assistindo", "Assistido"),
    "series": ("Quero assistir", "Assistindo", "Assistido"),
    "animes": ("Quero assistir", "Assistindo", "Assistido"),
    "livros": ("Quero ler", "Lendo", "Lido"),
    "mangas": ("Quero ler", "Lendo", "Lido"),
}


class BacklogValidationError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise BacklogValidationError("obra_id", "Escolha uma obra do catálogo.")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise BacklogValidationError("obra_id", "Escolha uma obra do catálogo.") from None
    if not 1 <= result <= 2**63 - 1:
        raise BacklogValidationError("obra_id", "Esta obra não está no catálogo.")
    return result


def validated_values(data, current=None):
    defaults = current or {"status": "planned", "visibility": "private", "progress": None, "progress_unit": None}
    values = {name: data.get(name, defaults[name]) for name in ("status", "visibility", "progress", "progress_unit")}
    if not isinstance(values["status"], str) or values["status"] not in STATUSES:
        raise BacklogValidationError("status", "Escolha um status válido.")
    if values["visibility"] not in ("private", "public"):
        raise BacklogValidationError("visibility", "Escolha uma visibilidade válida.")
    progress = values["progress"]
    if progress in (None, ""):
        values["progress"] = None
    else:
        if isinstance(progress, bool) or not isinstance(progress, (str, int)):
            raise BacklogValidationError("progress", "Use um progresso inteiro entre 0 e 100000.")
        try:
            progress = int(progress)
        except (TypeError, ValueError):
            raise BacklogValidationError("progress", "Use um progresso inteiro entre 0 e 100000.") from None
        if not 0 <= progress <= 100000:
            raise BacklogValidationError("progress", "Use um progresso inteiro entre 0 e 100000.")
        values["progress"] = progress
    if values["progress_unit"] in (None, ""):
        values["progress_unit"] = None
    elif not isinstance(values["progress_unit"], str) or values["progress_unit"] not in UNITS:
        raise BacklogValidationError("progress_unit", "Escolha horas, episódios ou capítulos.")
    return values


def get_owned_item(user_id, item_id):
    if not 1 <= item_id <= 2**63 - 1:
        raise NotFound()
    item = get_db().execute(select(BacklogItem).where(
        BacklogItem.id == item_id, BacklogItem.user_id == user_id)).fetchone()
    if item is None:
        raise NotFound()
    return item


def add_item(user_id, data):
    from ..settings.service import get_preferences
    work_id = positive_id(data.get("obra_id", data.get("work_id")))
    db = get_db()
    insert = pg_insert if db.dialect == "postgresql" else sqlite_insert
    with db:
        require_owner_session(lock_owner(db,user_id))
        work_statement = select(Work.id).where(Work.id == work_id, Work.active == 1)
        if db.dialect == 'postgresql':
            work_statement = work_statement.with_for_update()
        if db.execute(work_statement).fetchone() is None:
            raise NotFound("Esta obra não está no catálogo.")
        if 'visibility' not in data:
            data = {**data, 'visibility': get_preferences(user_id)['backlog_visibility']}
        values = validated_values(data)
        new_id = db.execute(insert(BacklogItem).values(user_id=user_id, work_id=work_id, **values)
                            .on_conflict_do_nothing(index_elements=["user_id", "work_id"])
                            .returning(BacklogItem.id)).scalar()
        if new_id is not None:
            category = db.execute(select(Work.categoria_id).where(Work.id==work_id)).scalar()
            record_action(db,user_id,'work_completed' if values['status']=='completed' else 'activity',utcnow(),
                work_id=work_id,category_id=category)
    item = db.execute(select(BacklogItem).where(
        BacklogItem.user_id == user_id, BacklogItem.work_id == work_id)).fetchone()
    return item, new_id is not None


def update_item(user_id, item_id, data):
    db = get_db()
    with db:
        require_owner_session(lock_owner(db,user_id))
        item = get_owned_item(user_id,item_id)
        values = validated_values(data,item)
        changed = any(item[field]!=value for field,value in values.items())
        db.execute(update(BacklogItem).where(BacklogItem.id == item_id, BacklogItem.user_id == user_id)
                   .values(**values, updated_at=utcnow()))
        if changed:
            category = db.execute(select(Work.categoria_id).where(Work.id==item['work_id'])).scalar()
            record_action(db,user_id,'work_completed' if values['status']=='completed' and item['status']!='completed' else 'activity',
                utcnow(),work_id=item['work_id'],category_id=category)
    return get_owned_item(user_id, item_id)


def remove_item(user_id, item_id):
    get_owned_item(user_id, item_id)
    db = get_db()
    with db:
        db.execute(delete(BacklogItem).where(BacklogItem.id == item_id, BacklogItem.user_id == user_id))


def collection_owner(username):
    if not storable_text(username):
        raise NotFound()
    owner = get_db().execute(select(User.id, User.username, User.nome).where(
        func.upper(User.username) == username.upper())).fetchone()
    if owner is None:
        raise NotFound()
    return owner


def categories():
    return get_db().execute(select(Category).order_by(Category.id)).fetchall()


def filters_from_args(args):
    category = args.get("categoria", "")
    query = args.get('q', '')
    valid_categories = {row["slug"] for row in categories()}
    return {
        "status": args.get("status", "") if args.get("status", "") in STATUSES else "",
        "categoria": category if category in valid_categories else "",
        "q": query.strip()[:120] if storable_text(query) else '',
    }


def _filter(statement, filters):
    if filters["categoria"]:
        statement = statement.where(Category.slug == filters["categoria"])
    if filters["q"]:
        statement = statement.where(func.coalesce(Work.search_title, func.lower(Work.titulo))
                                    .contains(filters["q"].casefold(), autoescape=True))
    return statement


def collection_items(user_id, filters, *, public_only=False):
    statement = select(BacklogItem, Work.titulo, Work.capa, Category.slug.label("category_slug"),
                       Category.nome.label("category_name")).join(Work, Work.id == BacklogItem.work_id)
    statement = statement.join(Category, Category.id == Work.categoria_id).where(BacklogItem.user_id == user_id)
    if public_only:
        statement = statement.where(BacklogItem.visibility == "public")
    if filters["status"]:
        statement = statement.where(BacklogItem.status == filters["status"])
    return get_db().execute(_filter(statement, filters).order_by(BacklogItem.updated_at.desc(), BacklogItem.id.desc())).fetchall()


def status_counts(user_id, *, public_only=False):
    statement = select(BacklogItem.status, func.count().label("total")).where(BacklogItem.user_id == user_id)
    if public_only:
        statement = statement.where(BacklogItem.visibility == "public")
    rows = get_db().execute(statement.group_by(BacklogItem.status)).fetchall()
    counts = {status: 0 for status in STATUSES}
    counts.update({row["status"]: row["total"] for row in rows})
    return counts


def catalog_items(user_id, filters):
    statement = select(Work, Category.slug.label("category_slug"), Category.nome.label("category_name"),
                       BacklogItem.id.label("backlog_id")).join(Category, Category.id == Work.categoria_id)
    statement = statement.outerjoin(BacklogItem, and_(BacklogItem.work_id == Work.id,
                                                     BacklogItem.user_id == user_id))
    statement = statement.where(Work.active == 1)
    return get_db().execute(_filter(statement, filters).order_by(Category.id, Work.titulo)).fetchall()


def status_label(status, category):
    if status in ("planned", "in_progress", "completed") and category in VERBS:
        return VERBS[category][("planned", "in_progress", "completed").index(status)]
    return STATUSES[status]
