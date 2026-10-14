"""Catalog writes serialize duplicates and recheck locked administrator sessions."""
from math import ceil

from sqlalchemy import func, insert, select, update
from werkzeug.exceptions import Forbidden, NotFound

from criticard.backlog.models import BacklogItem
from criticard.catalog_images import cover_metadata_for_work, default_cover_for_work
from criticard.db import get_db
from criticard.models import Card, Category, User, Work, utcnow
from criticard.privacy.cleanup import queue_image
from criticard.security import valid_session_identity
from criticard.storage import valid_image_name
from criticard.validation import FormValidationError, storable_text


class CatalogSessionExpired(ValueError):
    """The current credentials no longer authorize the administrative write."""


def categories():
    return get_db().execute(select(Category).order_by(Category.id)).fetchall()


def filters_from_args(args):
    query = args.get('q', '')
    category = args.get('categoria', '')
    status = args.get('status', 'active')
    return {'q': query.strip()[:120] if storable_text(query) else '',
            'categoria': category if category in {row['slug'] for row in categories()} else '',
            'status': status if status in {'active', 'archived', 'all'} else 'active'}


def _work_statement():
    return select(Work, Category.nome.label('category_name'),
        Category.slug.label('category_slug')).join(Category, Category.id == Work.categoria_id)


def _decorate(work):
    return dict(work, title=work['titulo'], **cover_metadata_for_work(work))


def _valid_id(work_id):
    if isinstance(work_id, bool) or not isinstance(work_id, int) or not 1 <= work_id <= 2**63 - 1:
        raise NotFound()
    return work_id


def get_work(work_id, *, locked=False):
    statement = _work_statement().where(Work.id == _valid_id(work_id))
    if locked and get_db().dialect == 'postgresql':
        statement = statement.with_for_update(of=Work)
    work = get_db().execute(statement).fetchone()
    if work is None:
        raise NotFound()
    return _decorate(work)


def usage_for_work(work_id):
    _valid_id(work_id)
    db = get_db()
    return {'cards': db.execute(select(func.count()).select_from(Card).where(Card.obra_id == work_id)).scalar(),
            'backlog': db.execute(select(func.count()).select_from(BacklogItem).where(BacklogItem.work_id == work_id)).scalar()}


def list_works(filters, *, page=1, per_page=20):
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    per_page = max(1, min(100, per_page))
    statement = _work_statement()
    if filters['status'] != 'all':
        statement = statement.where(Work.active == (0 if filters['status'] == 'archived' else 1))
    if filters['categoria']:
        statement = statement.where(Category.slug == filters['categoria'])
    if filters['q']:
        statement = statement.where(func.coalesce(Work.search_title, func.lower(Work.titulo))
            .contains(filters['q'].casefold(), autoescape=True))
    db = get_db()
    total = db.execute(select(func.count()).select_from(statement.subquery())).scalar()
    pages = max(1, ceil(total / per_page))
    page = min(page, pages)
    statement = statement.add_columns(
        select(func.count()).select_from(Card).where(Card.obra_id == Work.id)
            .correlate(Work).scalar_subquery().label('card_count'),
        select(func.count()).select_from(BacklogItem).where(BacklogItem.work_id == Work.id)
            .correlate(Work).scalar_subquery().label('backlog_count'))
    items = db.execute(statement.order_by(Category.id, Work.titulo, Work.id)
        .limit(per_page).offset((page - 1) * per_page)).fetchall()
    return {'items': [_decorate(work) for work in items], 'page': page,
            'pages': pages, 'total': total, 'per_page': per_page}


def _lock_administrator(administrator_id, session_data):
    db = get_db()
    if db.dialect == 'sqlite':
        user = db.execute(update(User).where(User.id == administrator_id)
            .values(session_version=User.session_version).returning(*User.__table__.columns)).fetchone()
    else:
        user = db.execute(select(User).where(User.id == administrator_id).with_for_update()).fetchone()
    if session_data.get('usuario_id') != administrator_id or not valid_session_identity(user, session_data):
        raise CatalogSessionExpired()
    if user['admin'] != 1:
        raise Forbidden()
    # All catalog writes take the same ascending category locks before any work
    # lock. This keeps Unicode casefold duplicate checks atomic on PostgreSQL;
    # SQLite's owner UPDATE already holds its single writer lock. No historical
    # titles need rewriting and inactive titles remain reserved for restoration.
    if db.dialect == 'postgresql':
        db.execute(select(Category.id).order_by(Category.id).with_for_update()).fetchall()


def _validated_values(data, *, work_id=None):
    raw_title = data.get('titulo', '')
    title = raw_title.strip() if isinstance(raw_title, str) else ''
    if not storable_text(title) or not 1 <= len(title) <= 120:
        raise FormValidationError('titulo', 'Título: preencha entre 1 e 120 caracteres.')
    raw_category = data.get('categoria_id', '')
    try:
        category_id = int(raw_category)
    except (TypeError, ValueError):
        raise FormValidationError('categoria_id', 'Escolha uma categoria válida.') from None
    db = get_db()
    if isinstance(raw_category, bool) or not 1 <= category_id <= 2**63 - 1 or db.execute(
            select(Category.id).where(Category.id == category_id)).fetchone() is None:
        raise FormValidationError('categoria_id', 'Escolha uma categoria válida.')
    existing = db.execute(select(Work.id, Work.titulo, Work.active).where(Work.categoria_id == category_id)).fetchall()
    for work in existing:
        if work['id'] != work_id and work['titulo'].strip().casefold() == title.casefold():
            message = 'Já existe uma obra com esse título nesta categoria.'
            if work['active'] == 0:
                message += ' A obra está retirada; reative o cadastro existente.'
            raise FormValidationError('titulo', message)
    return {'titulo': title, 'categoria_id': category_id, 'search_title': title.casefold()}


def _validated_cover(filename, *, required=False):
    if filename is None and not required:
        return None
    if not valid_image_name(filename):
        raise FormValidationError('capa', 'Escolha uma imagem de capa.')
    return filename


def create_work(administrator_id, session_data, data, cover_filename):
    db = get_db()
    with db:
        _lock_administrator(administrator_id, session_data)
        values = _validated_values(data)
        cover = _validated_cover(cover_filename, required=True)
        work_id = db.execute(insert(Work).values(**values, capa=cover, created_at=utcnow()).returning(Work.id)).scalar()
    return get_work(work_id)


def edit_work(administrator_id, session_data, work_id, data, cover_filename=None):
    _valid_id(work_id)
    db = get_db()
    with db:
        _lock_administrator(administrator_id, session_data)
        current = get_work(work_id, locked=True)
        values = _validated_values(data, work_id=work_id)
        cover = _validated_cover(cover_filename)
        # Resolve the previous artwork before changing its title/category.
        values['capa'] = cover or default_cover_for_work(current)
        db.execute(update(Work).where(Work.id == work_id).values(**values))
        if cover and current['capa'] != cover:
            queue_image('cover', current['capa'])
    return get_work(work_id)


def retire_work(administrator_id, session_data, work_id):
    _valid_id(work_id)
    db = get_db()
    with db:
        _lock_administrator(administrator_id, session_data)
        get_work(work_id, locked=True)
        db.execute(update(Work).where(Work.id == work_id).values(active=0))
    return get_work(work_id)


def restore_work(administrator_id, session_data, work_id):
    _valid_id(work_id)
    db = get_db()
    with db:
        _lock_administrator(administrator_id, session_data)
        current = get_work(work_id, locked=True)
        _validated_values(current, work_id=work_id)
        db.execute(update(Work).where(Work.id == work_id).values(active=1))
    return get_work(work_id)
