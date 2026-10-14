"""CSRF-protected administrative catalog pages and image uploads."""
from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

from criticard.db import get_db
from criticard.form_security import attempt_budget
from criticard.privacy.cleanup import cleanup_images, queue_image
from criticard.security import admin_required
from criticard.uploads import save_image
from criticard.validation import FormValidationError
from . import service

bp = Blueprint('admin_catalog', __name__)


def _form_context(work=None, errors=None):
    values = {key: request.form.get(key, work[key] if work else '') for key in ('titulo', 'categoria_id')}
    return {'values': values, 'work': work, 'editing': work is not None,
            'field_errors': errors or {}, 'categories': service.categories(),
            'cover_url': work['cover_url'] if work else url_for('static', filename='default-cover.svg'),
            'cover_art': work['cover_art'] if work else None}


def _budget_response(template, context):
    retry = attempt_budget('settings_security')
    if retry:
        flash('Muitas tentativas. Aguarde alguns minutos e tente novamente.', 'error')
        return render_template(template, **context), 429, {'Retry-After': str(retry)}
    return None


def _expired_session():
    session.clear()
    flash('Sua sessão expirou. Entre novamente para continuar.', 'error')
    return redirect(url_for('auth.index'))


def _discard_upload(filename):
    if filename:
        db = get_db()
        with db:
            queue_image('cover', filename)
        cleanup_images()


def _finish_cleanup():
    report = cleanup_images()
    if report['failed']:
        flash('Há capas com remoção pendente no armazenamento. A equipe precisa concluir a limpeza.', 'info')


@bp.get('/admin/obras')
@admin_required
def index():
    filters = service.filters_from_args(request.args)
    return render_template('admin/catalog/index.html',
        listing=service.list_works(filters, page=request.args.get('page', '1')),
        categories=service.categories(), filters=filters)


@bp.route('/admin/obras/nova', methods=['GET', 'POST'])
@admin_required
def create():
    errors = {}
    if request.method == 'POST':
        limited = _budget_response('admin/catalog/form.html', _form_context())
        if limited:
            return limited
        filename = None
        try:
            try:
                filename = save_image(request.files.get('capa'), current_app.config['CAPA_FOLDER'], required=True)
            except ValueError as error:
                raise FormValidationError('capa', str(error)) from error
            service.create_work(g.user['id'], session, request.form, filename)
        except FormValidationError as error:
            _discard_upload(filename)
            errors[error.field] = str(error)
        except service.CatalogSessionExpired:
            _discard_upload(filename)
            return _expired_session()
        except Exception:
            _discard_upload(filename)
            raise
        else:
            flash('Obra cadastrada no catálogo.', 'success')
            return redirect(url_for('admin_catalog.index'))
    return render_template('admin/catalog/form.html', **_form_context(errors=errors))


@bp.route('/admin/obras/<int:work_id>/editar', methods=['GET', 'POST'])
@admin_required
def edit(work_id):
    work = service.get_work(work_id)
    errors = {}
    if request.method == 'POST':
        limited = _budget_response('admin/catalog/form.html', _form_context(work))
        if limited:
            return limited
        filename = None
        try:
            try:
                filename = save_image(request.files.get('capa'), current_app.config['CAPA_FOLDER'])
            except ValueError as error:
                raise FormValidationError('capa', str(error)) from error
            service.edit_work(g.user['id'], session, work_id, request.form, filename)
        except FormValidationError as error:
            _discard_upload(filename)
            errors[error.field] = str(error)
        except service.CatalogSessionExpired:
            _discard_upload(filename)
            return _expired_session()
        except Exception:
            _discard_upload(filename)
            raise
        else:
            _finish_cleanup()
            flash('Obra atualizada.', 'success')
            return redirect(url_for('admin_catalog.index'))
    return render_template('admin/catalog/form.html', **_form_context(work, errors))


def _delete_context(work, errors=None):
    return {'work': work, 'usage': service.usage_for_work(work['id']),
            'will_archive': True, 'field_errors': errors or {}}


@bp.route('/admin/obras/<int:work_id>/excluir', methods=['GET', 'POST'])
@admin_required
def delete(work_id):
    work = service.get_work(work_id)
    errors = {}
    if request.method == 'POST':
        limited = _budget_response('admin/catalog/delete.html', _delete_context(work))
        if limited:
            return limited
        if request.form.get('confirm') != '1':
            errors['confirm'] = 'Confirme a retirada desta obra do catálogo.'
        else:
            try:
                service.retire_work(g.user['id'], session, work_id)
            except service.CatalogSessionExpired:
                return _expired_session()
            flash('Obra retirada do catálogo. As críticas e coleções foram preservadas.', 'success')
            return redirect(url_for('admin_catalog.index', status='archived'))
    return render_template('admin/catalog/delete.html', **_delete_context(work, errors))


@bp.post('/admin/obras/<int:work_id>/reativar')
@admin_required
def restore(work_id):
    work = service.get_work(work_id)
    filters = service.filters_from_args(request.args)
    limited = _budget_response('admin/catalog/index.html', {
        'listing': service.list_works(filters), 'categories': service.categories(), 'filters': filters})
    if limited:
        return limited
    try:
        service.restore_work(g.user['id'], session, work['id'])
    except service.CatalogSessionExpired:
        return _expired_session()
    except FormValidationError as error:
        flash(str(error), 'error')
        return redirect(url_for('admin_catalog.index', status='archived'))
    flash('Obra reativada no catálogo.', 'success')
    return redirect(url_for('admin_catalog.index'))
