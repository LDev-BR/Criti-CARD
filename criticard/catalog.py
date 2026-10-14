"""Catalog reads and validated selections; seed data lives in migrations."""
from sqlalchemy import select

from .catalog_images import cover_metadata_for_work
from .db import get_db
from .models import Category, Work
from .validation import FormValidationError


def get_catalog():
    db = get_db()
    categories = db.execute(select(Category).order_by(Category.id)).fetchall()
    works = db.execute(select(Work).where(Work.active == 1).order_by(Work.titulo)).fetchall()
    result = []
    for category in categories:
        catalog_works = []
        for work in works:
            if work['categoria_id'] == category['id']:
                entry = dict(work, category_slug=category['slug'])
                entry.update(cover_metadata_for_work(entry))
                catalog_works.append(entry)
        result.append(dict(category, works=catalog_works))
    return result


def selected_work(form,card=None):
    raw_id = form.get('obra_id',str(card['obra_id'] or '') if card else '')
    if not raw_id and card is not None and not card['obra_id']:
        return None
    try:
        work_id = int(raw_id)
    except (ValueError,TypeError):
        raise FormValidationError('obra_id','Escolha uma obra do catálogo.') from None
    if not 1 <= work_id <= 2**63-1:
        raise FormValidationError('obra_id','Esta obra não está no catálogo. Escolha outra.')
    work = get_db().execute(select(Work,Category.nome.label('categoria_nome'),
                                  Category.slug.label('category_slug')).join(Category).where(Work.id == work_id)).fetchone()
    if work is None or (work['active'] != 1 and (card is None or card['obra_id'] != work_id)):
        raise FormValidationError('obra_id','Esta obra não está no catálogo. Escolha outra.')
    category = form.get('categoria_id','')
    if category and category != str(work['categoria_id']):
        raise FormValidationError('categoria_id','A obra escolhida não pertence a esta categoria.')
    return dict(work, **cover_metadata_for_work(work))
