"""Public notice and a private channel separate from general support."""
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for

from criticard.form_security import attempt_budget
from criticard.security import admin_required, login_required, wants_json
from . import service

bp = Blueprint('privacy', __name__)


def _payload():
    payload = request.get_json(silent=True) if request.is_json else request.form
    return payload if hasattr(payload, 'get') else {}


def _budget(scope):
    retry = attempt_budget(scope)
    if retry:
        raise service.PrivacyError('Muitos envios. Aguarde alguns minutos e tente novamente.', status=429, retry=retry)


@bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@bp.errorhandler(service.PrivacyError)
def privacy_error(error):
    if wants_json():
        response = jsonify(error=str(error), field=error.field)
    elif error.status in (401, 403, 404):
        abort(error.status)
    elif request.endpoint == 'privacy.admin_detail':
        item = service.serialize(service.get_request(request.view_args['protocol'], admin=True), detail=True, admin=True)
        response = current_app.make_response(render_template('privacy/detail.html', item=item, admin=True,
            statuses=service.STATUSES, values=_safe_values(), error=error))
    else:
        response = current_app.make_response(render_template('privacy/requests.html',
            listing=service.request_list(request.args.get('page')), kinds=service.KINDS,
            values=_safe_values(), error=error))
    response.status_code = error.status
    if error.retry:
        response.headers['Retry-After'] = str(error.retry)
    return response


def _safe_values():
    # Private free text never enters the cookie/flash; preserve bounded form input
    # in this response only. Templates escape all values.
    data = _payload()
    return {key: value for key in ('kind', 'body', 'status')
        if isinstance(value := data.get(key, ''), str) and len(value) <= 3000}


@bp.get('/privacidade')
def policy():
    return render_template('privacy/policy.html', controller=current_app.config['PRIVACY_CONTROLLER_NAME'],
        contact_email=current_app.config['PRIVACY_CONTACT_EMAIL'],
        uses_s3=current_app.config.get('STORAGE_BACKEND') == 's3',
        uses_mail=current_app.config.get('ACCOUNT_MAIL_BACKEND') == 'smtp')


@bp.route('/privacidade/pedidos', methods=['GET', 'POST'])
@login_required
def requests():
    if request.method == 'POST':
        _budget('privacy_request')
        data = _payload()
        item = service.serialize(service.create_request(data.get('kind'), data.get('body')), detail=True)
        if wants_json():
            response = jsonify(request=item)
            response.status_code = 201
            response.headers['Location'] = url_for('privacy.detail', protocol=item['protocol'])
            return response
        flash('Pedido registrado. Guarde seu protocolo e acompanhe a resposta aqui.', 'success')
        return redirect(url_for('privacy.detail', protocol=item['protocol']), code=303)
    listing = service.request_list(request.args.get('page'))
    if wants_json():
        return jsonify(listing)
    return render_template('privacy/requests.html', listing=listing, kinds=service.KINDS, values={}, error=None)


@bp.get('/privacidade/pedidos/<protocol>')
@login_required
def detail(protocol):
    item = service.serialize(service.get_request(protocol), detail=True)
    if wants_json():
        return jsonify(request=item)
    return render_template('privacy/detail.html', item=item, admin=False, error=None)


@bp.get('/admin/privacidade')
@admin_required
def admin_requests():
    listing = service.request_list(request.args.get('page'), admin=True, status=request.args.get('status', ''))
    if wants_json():
        return jsonify(listing)
    return render_template('privacy/admin.html', listing=listing, statuses=service.STATUSES)


@bp.route('/admin/privacidade/<protocol>', methods=['GET', 'POST'])
@admin_required
def admin_detail(protocol):
    if request.method == 'POST':
        _budget('privacy_admin')
        data = _payload()
        record = service.reply_to_request(protocol, data.get('status'), data.get('body'))
        if wants_json():
            return jsonify(request=service.serialize(record, detail=True))
        flash('Resposta registrada e disponível para o titular.', 'success')
        return redirect(url_for('privacy.admin_detail', protocol=protocol), code=303)
    item = service.serialize(service.get_request(protocol, admin=True), detail=True, admin=True)
    if wants_json():
        return jsonify(request=item)
    return render_template('privacy/detail.html', item=item, admin=True,
        statuses=service.STATUSES, values={}, error=None)
