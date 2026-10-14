"""Portable public card queries, with bounded pagination and literal search."""
from dataclasses import dataclass
from datetime import timedelta
from math import ceil

from flask import abort, g
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from .db import get_db
from .catalog_images import default_cover_for_work
from .models import Card, Category, User, Work, utcnow
from .progression.presentation import attach_public_styles

PAGE_SIZE = 12


@dataclass
class CardPage:
    items: list
    number: int
    total: int

    @property
    def pages(self):
        return max(1,ceil(self.total / PAGE_SIZE))


def card_query():
    return select(Card,User.username,User.nome,User.imagem.label('autor_imagem'),Work.categoria_id,
                  Category.nome.label('categoria_nome'), Category.slug.label('category_slug'),
                  Work.titulo.label('work_titulo'), Work.capa.label('work_capa')).join(User,User.id == Card.author_id).outerjoin(
                      Work,Work.id == Card.obra_id).outerjoin(Category,Category.id == Work.categoria_id)


def _catalog_card(card):
    # Keep historical database values intact; linked cards display the current
    # catalog identity and its administrator-controlled cover in every feed.
    if card['work_titulo'] is not None and not card['archived']:
        card['titulo'] = card['work_titulo']
        card['capa'] = default_cover_for_work({'titulo': card['work_titulo'],
            'capa': card['work_capa'], 'category_slug': card['category_slug']})
    return card


def get_cards(page=1,author_id=None,query='',category='',work=None,minimum=0,sort='recent',following_id=None):
    db = get_db()
    statement = card_query().where(Card.archived == 0)
    if getattr(g, 'user', None):
        from .social.models import Block
        statement = statement.where(~exists(select(Block.id).where(or_(
            and_(Block.user_id == g.user['id'],Block.target_id == Card.author_id),
            and_(Block.target_id == g.user['id'],Block.user_id == Card.author_id)))))
    if author_id is not None:
        statement = statement.where(Card.author_id == author_id)
    if category:
        statement = statement.where(Category.slug == category)
    if work is not None:
        statement = statement.where(Card.obra_id == work)
    if minimum > 0:
        statement = statement.where(Card.nota >= minimum)
    if query:
        pattern = '%' + query.casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        title = (func.casefold(func.coalesce(Work.titulo, Card.titulo)) if db.dialect == 'sqlite' else
                 func.coalesce(Work.search_title, func.lower(Work.titulo), Card.search_title, func.lower(Card.titulo)))
        name = func.casefold(User.nome) if db.dialect == 'sqlite' else func.coalesce(User.search_name,func.lower(User.nome))
        statement = statement.where(or_(title.like(pattern,escape='\\'),func.lower(User.username).like(pattern,escape='\\'),name.like(pattern,escape='\\')))
    if following_id is not None:
        from .social.models import CategoryFollow, Follow, WorkFollow
        statement = statement.where(User.active == 1,
            or_(Card.obra_id.is_(None), Work.active == 1))
        statement = statement.where(or_(
            Card.author_id.in_(select(Follow.target_id).where(Follow.user_id == following_id)),
            Card.obra_id.in_(select(WorkFollow.work_id).where(WorkFollow.user_id == following_id)),
            Work.categoria_id.in_(select(CategoryFollow.category_id).where(CategoryFollow.user_id == following_id))))
    if sort == 'popular':
        from .social.models import CardLike, Comment
        statement = statement.where(Card.created_at >= utcnow() - timedelta(days=7),
            User.active == 1, or_(Card.obra_id.is_(None), Work.active == 1))
        liker = aliased(User)
        commenter = aliased(User)
        likes = select(func.count(CardLike.id)).join(liker, liker.id == CardLike.user_id).where(
            CardLike.card_id == Card.id, liker.active == 1).scalar_subquery()
        comments = select(func.count(Comment.id)).join(commenter,
            commenter.id == Comment.author_id).where(Comment.card_id == Card.id,
                commenter.active == 1).scalar_subquery()
        popular_score = 2 * likes + 3 * comments
        ordering = (popular_score.desc(), Card.created_at.desc(), Card.id.desc())
    else:
        ordering = {'recent':(Card.id.desc(),),'oldest':(Card.id.asc(),),
                    'highest':(Card.nota.desc(),Card.id.desc()),'lowest':(Card.nota.asc(),Card.id.desc())}
    total = db.execute(select(func.count()).select_from(statement.subquery())).scalar()
    result = CardPage([],max(1,page),total)
    if result.number > result.pages:
        abort(404)
    order = ordering if sort == 'popular' else ordering.get(sort, ordering['recent'])
    result.items = [_catalog_card(card) for card in db.execute(statement.order_by(*order).limit(PAGE_SIZE).offset((result.number-1)*PAGE_SIZE)).fetchall()]
    attach_public_styles(result.items)
    return result


def get_author_cards(author_id, *, archived=False):
    return attach_public_styles([_catalog_card(card) for card in get_db().execute(card_query().where(Card.author_id == author_id,
        Card.archived == int(archived)).order_by(Card.id.desc())).fetchall()])


def get_card(card_id):
    if not isinstance(card_id,int) or not 1 <= card_id <= 2**63-1:
        abort(404)
    card = get_db().execute(card_query().where(Card.id == card_id)).fetchone()
    if card is None:
        abort(404)
    if card['archived'] and (not getattr(g, 'user', None) or g.user['id'] != card['author_id']):
        abort(404)
    if getattr(g, 'user', None):
        from .social.service import users_blocked
        if users_blocked(g.user['id'],card['author_id']):
            abort(404)
    return attach_public_styles([_catalog_card(card)])[0]
