from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from ..models import utcnow
from ..persistence import get_db
from ..security import login_required, valid_session_identity, wants_json
from ..settings.service import SettingsError, get_preferences
from ..settings.views import _payload
from .queries import achievement_list, event_page, journey_summary, reward_inventory, save_equipment
from .service import claim_notice, lock_owner, sync_user
from .types import ProgressionError
from .presentation import notice_message

bp = Blueprint('progression',__name__)


@bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.errorhandler(ProgressionError)
@bp.errorhandler(SettingsError)
def error_response(error):
    if wants_json():
        return jsonify(error=str(error),field=error.field),error.status
    abort(error.status,description=str(error))


@bp.get('/jornada')
@login_required
def index():
    if set(request.args)-{'page','conquistas'}:
        abort(404)
    raw = request.args.get('page','1')
    if not raw.isascii() or not raw.isdecimal() or len(raw)>7:
        abort(404)
    state = request.args.get('conquistas','all')
    context = dict(summary=journey_summary(g.user['id']),events=event_page(g.user['id'],int(raw)),
        achievements=achievement_list(g.user['id'],state),achievement_state=state,
        rewards=reward_inventory(g.user['id']),preferences=get_preferences(g.user['id']))
    if wants_json():
        return jsonify(**context)
    return render_template('progression/index.html',**context)


@bp.post('/jornada/sincronizar')
@login_required
def sync():
    payload = request.get_json(silent=True) if request.is_json else {k:v for k,v in request.form.items() if k!='csrf_token'}
    if payload != {} or not isinstance(payload,dict):
        raise ProgressionError('A atualização não recebe pontos nem identificadores.')
    with get_db() as db:
        owner = lock_owner(db,g.user['id'])
        if not valid_session_identity(owner,session):
            abort(401)
        award = sync_user(db,owner['id'],utcnow())
        notice = claim_notice(db,owner['id'],utcnow())
    message = notice_message(notice)
    if wants_json():
        summary = journey_summary(owner['id'])
        return jsonify(summary=summary,summary_html=render_template('progression/summary.html',summary=summary),
            notice=message,changed=award.awarded>0 or notice is not None)
    if message:
        flash(message,'success')
    return redirect(url_for('progression.index'))


@bp.post('/jornada/personalizar')
@login_required
def personalize():
    preferences = save_equipment(g.user['id'],_payload('jornada',boolean_fields=('progression_public',)))
    if wants_json():
        return jsonify(preferences=preferences,message='Personalização salva.')
    flash('Personalização salva.','success')
    return redirect(url_for('progression.index',_anchor='personalizar'))
