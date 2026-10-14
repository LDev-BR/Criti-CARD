"""Session-owned settings forms and strict JSON updates."""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select

from ..db import get_db
from ..models import Category
from ..security import login_required, wants_json
from .schema import FIELDS, SECTIONS, SECTION_FIELDS
from .service import SettingsError, get_preferences, reset_preferences, save_preferences

bp = Blueprint('settings', __name__)


def _render(section, *, values=None, errors=None, status=200):
    fields = {name: dict(field) for name, field in FIELDS.items()}
    fields['feed_category']['choices'] = {'': 'Todas as categorias', **{
        row['slug']: row['nome'] for row in get_db().execute(select(Category.slug, Category.nome)
                                                           .order_by(Category.id)).fetchall()}}
    preferences = get_preferences(g.user['id'])
    from ..progression.queries import reward_inventory
    inventory = reward_inventory(g.user['id'])
    fields['progression_badge']['choices'] = {'':'Sem selo',**{
        item['slug']:item['name'] for item in inventory if item['kind']=='badge' and item['owned']}}
    blocked = None
    if section == 'bloqueados':
        from ..accounts.settings import blocked_users
        blocked = blocked_users(g.user['id'], request.args.get('q', ''), request.args.get('page', 1))
    return render_template('settings/index.html', active_section=section, preferences=preferences,
        sections=SECTIONS, fields=fields, section_fields=SECTION_FIELDS,
        values=preferences if values is None else values, errors=errors or {}, blocked=blocked,
        account_error=session.pop('_settings_account_error', None) if section == 'conta' else None), status


def _payload(section, *, boolean_fields=None):
    if request.is_json:
        value = request.get_json()
        return {name: item for name, item in value.items() if name != 'csrf_token'} if isinstance(value, dict) else value
    # Duplicate keys are ambiguous and must never silently choose a value.
    if any(len(request.form.getlist(name)) != 1 for name in request.form):
        raise SettingsError('Envie um único valor por opção.')
    values = {name: value for name, value in request.form.items() if name != 'csrf_token'}
    for name in SECTION_FIELDS.get(section, ()):
        if FIELDS[name]['kind'] == 'boolean':
            if boolean_fields is not None and name not in boolean_fields:
                continue
            value = values.get(name)
            if value is None:
                values[name] = False
            elif value in ('on', 'true', '1'):
                values[name] = True
            elif value in ('false', '0'):
                values[name] = False
            else:
                raise SettingsError('Escolha um valor válido para esta opção.', field=name)
        elif FIELDS[name]['kind'] == 'integer' and name in values:
            raw = values[name]
            if len(raw) > 3 or not raw.isascii() or not raw.isdecimal():
                raise SettingsError('Use uma nota inteira entre 0 e 100.', field=name)
            values[name] = int(raw)
    return values


@bp.get('/configuracoes')
@login_required
def index():
    section = request.args.get('secao', 'aparencia')
    if section not in SECTIONS:
        abort(404)
    if wants_json():
        return jsonify(preferences=get_preferences(g.user['id']), active_section=section)
    return _render(section)


@bp.post('/configuracoes/<section>')
@login_required
def save(section):
    if not SECTION_FIELDS.get(section):
        abort(404)
    values = None
    try:
        values = _payload(section)
        preferences = save_preferences(g.user['id'], section, values)
    except SettingsError as error:
        if wants_json():
            return jsonify(error=str(error), field=error.field), error.status
        safe_values = get_preferences(g.user['id'])
        if isinstance(values, dict):
            safe_values.update({name: value for name, value in values.items() if name in SECTION_FIELDS[section]})
        return _render(section, values=safe_values, errors={error.field or '_form': str(error)}, status=error.status)
    if wants_json():
        return jsonify(preferences=preferences, message='Preferências salvas.')
    flash('Preferências salvas.', 'success')
    return redirect(url_for('settings.index', secao=section))


@bp.post('/configuracoes/<section>/restaurar')
@login_required
def reset(section):
    if not SECTION_FIELDS.get(section):
        abort(404)
    payload = request.get_json() if request.is_json else {
        name: value for name, value in request.form.items() if name != 'csrf_token'}
    if payload != {}:
        if wants_json():
            return jsonify(error='A restauração não recebe opções.'), 400
        return _render(section, errors={'_form': 'A restauração não recebe opções.'}, status=400)
    preferences = reset_preferences(g.user['id'], section)
    if wants_json():
        return jsonify(preferences=preferences, message='Padrões restaurados para esta área.')
    flash('Padrões restaurados para esta área.', 'success')
    return redirect(url_for('settings.index', secao=section))
