"""Personal connections: progressive pages and the chat's public contact finder."""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from ..security import login_required
from ..storage import image_url
from ..validation import storable_text
from . import service
from .views import _boolean, _payload, _serialized, social_error, wants_json

bp = Blueprint('people', __name__)

TABS = {
    'amigos': {'key': 'friends', 'title': 'Seus amigos', 'label': 'Amigos', 'icon': 'users',
               'description': 'Uma boa conversa começa por aqui.', 'empty': 'Sua próxima amizade começa com um convite.',
               'hint': 'Encontre pessoas da comunidade e envie uma solicitação de amizade.'},
    'recebidas': {'key': 'incoming', 'title': 'Solicitações recebidas', 'label': 'Recebidas', 'icon': 'user-plus',
                  'description': 'Você decide quem faz parte do seu círculo.', 'empty': 'Tudo em dia por aqui.',
                  'hint': 'Novos convites de amizade aparecerão nesta lista.'},
    'enviadas': {'key': 'outgoing', 'title': 'Solicitações enviadas', 'label': 'Enviadas', 'icon': 'send',
                 'description': 'Os convites que estão aguardando uma resposta.', 'empty': 'Nenhum convite aguardando resposta.',
                 'hint': 'Seus pedidos ficam aqui até serem aceitos, recusados ou cancelados.'},
    'seguindo': {'key': 'following', 'title': 'Pessoas que você segue', 'label': 'Seguindo', 'icon': 'user-check',
                 'description': 'As opiniões que você acompanha no seu feed.', 'empty': 'Seu feed pode ganhar novas perspectivas.',
                 'hint': 'Siga pessoas para acompanhar as críticas delas no feed de seguidos.'},
    'seguidores': {'key': 'followers', 'title': 'Seus seguidores', 'label': 'Seguidores', 'icon': 'user',
                   'description': 'Pessoas que acompanham suas descobertas.', 'empty': 'Suas primeiras conexões vêm aí.',
                   'hint': 'Publique críticas e participe da comunidade para encontrar novos leitores.'},
    'descobrir': {'key': 'discover', 'title': 'Encontrar pessoas', 'label': 'Encontrar pessoas', 'icon': 'search',
                  'description': 'Descubra quem também gosta de boas histórias.', 'empty': 'Ainda não há outras pessoas por aqui.',
                  'hint': 'Os novos perfis da comunidade vão aparecer nesta lista.'},
}


def _connections():
    from . import connections
    return connections


def _tab(value):
    return value if isinstance(value, str) and value in TABS else 'amigos'


def _return_target(payload, target_id):
    if payload.get('context') == 'profile':
        user = service._require(service.User, target_id)
        return url_for('community.profile', username=user['username'])
    tab = _tab(payload.get('aba'))
    query = payload.get('q', '')
    query = query.strip() if storable_text(query) and len(query) <= 200 else ''
    requested = payload.get('page', '1')
    page = int(requested) if isinstance(requested, str) and len(requested) <= 7 and requested.isdecimal() else 1
    args = {'aba': tab}
    if query:
        args['q'] = query
    if page > 1:
        pages = _connections().list_connections(g.user['id'], TABS[tab]['key'], query)['pages']
        args['page'] = min(page, pages)
    return url_for('people.connections', **args)


def _result(data, payload, target_id, message):
    if wants_json():
        return jsonify(_serialized(data))
    flash(message, 'success')
    return redirect(_return_target(payload, target_id))


bp.register_error_handler(service.SocialError, social_error)


@bp.get('/conexoes')
@login_required
def connections():
    tab = _tab(request.args.get('aba'))
    page = max(1, request.args.get('page', 1, type=int) or 1)
    if page > 1_000_000:
        abort(404)
    data = _connections().list_connections(g.user['id'], TABS[tab]['key'], request.args.get('q', ''), page)
    data['people'] = [dict(person, avatar_url=image_url('avatar', person['imagem'])) for person in data['people']]
    if wants_json():
        return jsonify(_serialized(data))
    return render_template('social/connections.html', **data, active_tab=tab, tabs=TABS, tab_meta=TABS[tab])


@bp.get('/amigos')
@login_required
def friends():
    return redirect(url_for('people.connections', aba='amigos'))


@bp.get('/solicitacoes')
@login_required
def requests():
    return redirect(url_for('people.connections', aba='recebidas'))


@bp.post('/conexoes/<int:user_id>/amizade')
@login_required
def friendship(user_id):
    payload = _payload()
    state = _connections().change_friendship(g.user['id'], user_id, payload.get('action'))
    return _result({'friendship': state, 'counts': _connections().connection_counts(g.user['id'])},
                   payload, user_id, 'Amizade atualizada.')


@bp.post('/conexoes/<int:user_id>/seguir')
@login_required
def follow(user_id):
    payload = _payload()
    state = service.set_follow(g.user['id'], user_id, _boolean('following'))
    state['counts'] = _connections().connection_counts(g.user['id'])
    return _result(state, payload, user_id, 'Preferência de seguir atualizada.')
