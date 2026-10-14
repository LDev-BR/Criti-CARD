from dataclasses import asdict

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select

from ..models import User, utcnow
from ..persistence import get_db
from ..security import admin_required, wants_json
from .models import ExperienceEvent
from .queries import event_page, journey_summary
from .service import revoke_event
from .types import ProgressionError

bp = Blueprint('progression_admin',__name__)


@bp.after_request
def private_response(response):
    response.headers['Cache-Control']='no-store'
    return response


@bp.errorhandler(ProgressionError)
def error_response(error):
    if wants_json():
        return jsonify(error=str(error),field=error.field),error.status
    abort(error.status,description=str(error))


@bp.get('/admin/jornada/<int:user_id>')
@admin_required
def index(user_id):
    if not 1<=user_id<=2**63-1:
        abort(404)
    owner = get_db().execute(select(User.id,User.username).where(User.id==user_id)).fetchone()
    if owner is None:
        abort(404)
    raw = request.args.get('page','1')
    if not raw.isascii() or not raw.isdecimal() or len(raw)>7:
        abort(404)
    events = event_page(user_id,int(raw))
    reversed_ids = {row[0] for row in get_db().execute(select(ExperienceEvent.reverses_event_id)
        .where(ExperienceEvent.user_id==user_id,ExperienceEvent.reverses_event_id.is_not(None))).fetchall()}
    return render_template('admin/progression.html',owner=owner,summary=journey_summary(user_id),
        events=events,reversed_ids=reversed_ids)


@bp.post('/admin/jornada/eventos/<int:event_id>/revogar')
@admin_required
def revoke(event_id):
    data = request.get_json(silent=True) if request.is_json else {k:v for k,v in request.form.items() if k!='csrf_token'}
    if not isinstance(data,dict) or set(data)!={'reason'}:
        raise ProgressionError('Envie somente o motivo da correção.')
    with get_db() as db:
        result = revoke_event(db,g.user['id'],event_id,data['reason'],utcnow())
        owner = db.execute(select(ExperienceEvent.user_id).where(ExperienceEvent.id==event_id)).scalar()
    if wants_json():
        return jsonify(award=asdict(result),message='Correção registrada.')
    flash('Correção registrada. O histórico e as recompensas foram reconciliados.','success')
    return redirect(url_for('progression_admin.index',user_id=owner))
