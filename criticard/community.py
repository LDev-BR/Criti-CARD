"""Public community and profiles."""
from dataclasses import replace
from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from sqlalchemy import func, select

from .catalog import get_catalog
from .db import get_db
from .feed_filters import SORTS, normalized_filters
from .models import User
from .queries import get_cards
from .social.service import card_social_state, user_social_state
from .validation import storable_text

bp = Blueprint('community',__name__)


def page_number():
    try:
        page = max(1,int(request.args.get('page','1')))
        if page > 1_000_000:
            abort(404)
        return page
    except ValueError:
        return 1


@bp.get('/criticas')
def feed():
    catalog = get_catalog()
    args = dict(request.args)
    ignore_preferences = args.get('preferencias') == 'ignorar'
    custom_preferences = False
    if g.user:
        from .settings.schema import DEFAULTS
        mappings = {'feed': 'feed_source', 'ordem': 'feed_sort', 'categoria': 'feed_category', 'nota_min': 'feed_min_score'}
        custom_preferences = any(g.preferences[name] != DEFAULTS[name] for name in mappings.values())
        if not ignore_preferences:
            for parameter, name in mappings.items():
                args.setdefault(parameter, g.preferences[name])
    filters = replace(normalized_filters(args, catalog), ignore_preferences=ignore_preferences or custom_preferences)
    if filters.feed == 'following' and not g.user:
        return redirect(url_for('auth.index'))
    cards = get_cards(page_number(),query=filters.query,category=filters.category,work=filters.work,minimum=filters.minimum,sort=filters.sort,
                      following_id=g.user['id'] if filters.feed == 'following' else None)
    pagination_args = filters.url_args()
    return render_template('feed.html',cards=cards,query=filters.query,filters=filters,catalog=catalog,sort_options=SORTS,
                           feed_reset_url=url_for('community.feed', preferencias='ignorar') if filters.ignore_preferences else url_for('community.feed'),
                           pagination_endpoint='community.feed',pagination_args=pagination_args,
                           social_states=card_social_state([c['id'] for c in cards.items],g.user['id'] if g.user else None))


@bp.get('/perfil/<username>')
def profile(username):
    if not storable_text(username):
        abort(404)
    user = get_db().execute(select(User.id,User.username,User.nome,User.apelido,User.about,User.imagem).where(func.lower(User.username) == username.lower())).fetchone()
    if user is None:
        abort(404)
    cards = get_cards(page_number(),author_id=user['id'])
    from .progression.queries import public_styles
    profile_style = public_styles([user['id']])[user['id']]
    return render_template('profile.html',profile=user,cards=cards,
                           profile_style=profile_style,
                           user_social=user_social_state(user['id'],g.user['id'] if g.user else None),
                           social_states=card_social_state([c['id'] for c in cards.items],g.user['id'] if g.user else None),
                           pagination_endpoint='community.profile',pagination_args={'username':user['username']})
