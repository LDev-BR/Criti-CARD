"""Bounded public trends and personal follow previews for the welcome hub."""
from datetime import timedelta

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.orm import aliased

from ..db import get_db
from ..catalog_images import cover_metadata_for_work
from ..models import Card, Category, User, Work, utcnow
from ..social.models import Block, CardLike, CategoryFollow, Comment, Follow, WorkFollow


def _visible_cards(viewer_id):
    conditions = [Card.archived == 0, User.active == 1]
    if viewer_id is not None:
        conditions.append(~exists(select(Block.id).where(or_(and_(Block.user_id == viewer_id,
            Block.target_id == Card.author_id), and_(Block.target_id == viewer_id,
            Block.user_id == Card.author_id)))))
    return conditions


def trending_works(now=None, limit=8, viewer_id=None):
    now = now or utcnow()
    since = now - timedelta(days=7)
    db = get_db()
    author = aliased(User)
    recent = select(Card.obra_id.label('work_id'), func.count(Card.id).label('recent_reviews'),
        func.count(func.distinct(Card.author_id)).label('distinct_authors')).join(
        User, User.id == Card.author_id).where(Card.obra_id.is_not(None), Card.created_at >= since,
        *_visible_cards(viewer_id)).group_by(Card.obra_id).subquery()

    liker = aliased(User)
    like_conditions = [Card.obra_id.is_not(None), CardLike.created_at >= since,
        Card.archived == 0, liker.active == 1, author.active == 1]
    if viewer_id is not None:
        blocked_author = exists(select(Block.id).where(or_(and_(Block.user_id == viewer_id,
            Block.target_id == Card.author_id), and_(Block.target_id == viewer_id,
            Block.user_id == Card.author_id))))
        blocked_liker = exists(select(Block.id).where(or_(and_(Block.user_id == viewer_id,
            Block.target_id == CardLike.user_id), and_(Block.target_id == viewer_id,
            Block.user_id == CardLike.user_id))))
        like_conditions.extend((~blocked_author, ~blocked_liker))
    likes = select(Card.obra_id.label('work_id'), func.count(func.distinct(CardLike.user_id)).label(
        'recent_likers')).select_from(CardLike).join(Card, Card.id == CardLike.card_id).join(
        author, author.id == Card.author_id).join(liker, liker.id == CardLike.user_id).where(
        *like_conditions).group_by(Card.obra_id).subquery()

    commenter = aliased(User)
    comment_conditions = [Card.obra_id.is_not(None), Comment.created_at >= since,
        Card.archived == 0, commenter.active == 1, author.active == 1]
    if viewer_id is not None:
        blocked_author = exists(select(Block.id).where(or_(and_(Block.user_id == viewer_id,
            Block.target_id == Card.author_id), and_(Block.target_id == viewer_id,
            Block.user_id == Card.author_id))))
        blocked_commenter = exists(select(Block.id).where(or_(and_(Block.user_id == viewer_id,
            Block.target_id == Comment.author_id), and_(Block.target_id == viewer_id,
            Block.user_id == Comment.author_id))))
        comment_conditions.extend((~blocked_author, ~blocked_commenter))
    commenters = select(Card.obra_id.label('work_id'), func.count(func.distinct(Comment.author_id)).label(
        'recent_commenters')).select_from(Comment).join(Card, Card.id == Comment.card_id).join(
        author, author.id == Card.author_id).join(commenter, commenter.id == Comment.author_id).where(
        *comment_conditions).group_by(Card.obra_id).subquery()

    recent_reviews = func.coalesce(recent.c.recent_reviews, 0)
    distinct_authors = func.coalesce(recent.c.distinct_authors, 0)
    distinct_likers = func.coalesce(likes.c.recent_likers, 0)
    distinct_commenters = func.coalesce(commenters.c.recent_commenters, 0)
    score = 4 * recent_reviews + 2 * distinct_authors + distinct_likers + 2 * distinct_commenters
    rows = db.execute(select(Work.id, Work.titulo, Work.capa, Category.slug.label('category_slug'),
        Category.nome.label('category_name'), score.label('score'), recent_reviews.label('recent_reviews'),
        distinct_authors.label('distinct_authors'), distinct_likers.label('recent_likers'),
        distinct_commenters.label('recent_commenters')).join(Category, Category.id == Work.categoria_id)
        .outerjoin(recent, recent.c.work_id == Work.id).outerjoin(likes, likes.c.work_id == Work.id)
        .outerjoin(commenters, commenters.c.work_id == Work.id).where(
            Work.active == 1, recent_reviews > 0).order_by(score.desc(), recent_reviews.desc(),
                Work.created_at.desc().nullslast(), Work.id.desc()).limit(max(1, min(24, limit)))).fetchall()
    results = []
    for row in rows:
        reason = 'críticas recentes' if row['recent_reviews'] >= 2 else (
            'muitas discussões' if row['recent_commenters'] >= 2 else 'uma obra em descoberta')
        item = dict(row, reason=reason)
        item.update(cover_metadata_for_work(item))
        results.append(item)
    return results


def _recommended_communities(user_id, limit=5):
    from ..communities.models import Community, CommunityMembership
    db = get_db()
    followed = select(CategoryFollow.category_id).where(CategoryFollow.user_id == user_id) if user_id else None
    member_count = select(func.count()).select_from(CommunityMembership).join(
        User, User.id == CommunityMembership.user_id).where(
            CommunityMembership.community_id == Community.id, User.active == 1).scalar_subquery()
    preferred = (Community.category_id.in_(followed) if followed is not None else false())
    ordering = ([preferred.desc()] if followed is not None else []) + [
        member_count.desc(), Community.name, Community.id]
    rows = db.execute(select(Community.__table__, Category.nome.label('category_name'),
        member_count.label('member_count'), preferred.label('is_followed_theme')).outerjoin(
            Category, Category.id == Community.category_id).where(
                Community.archived == 0, Community.mode == 'open')
            .order_by(*ordering).limit(limit)).fetchall()
    return rows


def hub_context(user_id=None, now=None):
    now = now or utcnow()
    db = get_db()
    result = {'trending_works': trending_works(now, 8, user_id),
        'recommended_communities': _recommended_communities(user_id), 'followed_cards': [],
        'followed_works': [], 'followed_categories': [], 'followed_authors': [],
        'new_followed_category_works': []}
    if user_id is None:
        return result

    followed_works = db.execute(select(Work.id, Work.titulo, Work.capa,
        Category.slug.label('category_slug'), Category.nome.label('category_name')).join(
        WorkFollow, WorkFollow.work_id == Work.id).join(Category, Category.id == Work.categoria_id)
        .where(WorkFollow.user_id == user_id, Work.active == 1)
        .order_by(WorkFollow.created_at.desc(), Work.id).limit(6)).fetchall()
    result['followed_works'] = []
    for row in followed_works:
        item = dict(row)
        item.update(cover_metadata_for_work(item))
        result['followed_works'].append(item)
    result['followed_categories'] = db.execute(select(Category.id, Category.slug, Category.nome)
        .join(CategoryFollow, CategoryFollow.category_id == Category.id)
        .where(CategoryFollow.user_id == user_id).order_by(Category.nome).limit(10)).fetchall()
    result['followed_authors'] = db.execute(select(User.id, User.username, User.nome, User.imagem)
        .join(Follow, Follow.target_id == User.id).where(Follow.user_id == user_id,
            User.active == 1, ~exists(select(Block.id).where(or_(and_(Block.user_id == user_id,
                Block.target_id == User.id), and_(Block.target_id == user_id, Block.user_id == User.id)))))
        .order_by(Follow.created_at.desc(), User.id).limit(6)).fetchall()
    if result['followed_categories']:
        category_ids = [row['id'] for row in result['followed_categories']]
        result['new_followed_category_works'] = db.execute(select(Work.id, Work.titulo,
            Category.nome.label('category_name'), Category.slug.label('category_slug'))
            .join(Category, Category.id == Work.categoria_id).where(Work.active == 1,
                Work.categoria_id.in_(category_ids), Work.created_at.is_not(None))
            .order_by(Work.created_at.desc(), Work.id.desc()).limit(6)).fetchall()
    from ..queries import get_cards
    result['followed_cards'] = get_cards(1, following_id=user_id).items[:6]
    from ..social.service import card_social_state
    result['followed_card_states'] = card_social_state([card['id'] for card in result['followed_cards']], user_id)
    result['followed_cards'] = result['followed_cards']
    return result
