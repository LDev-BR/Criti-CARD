"""Administrator actions consult current database permissions."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, update
from werkzeug.security import check_password_hash

from .auth import find_identity
from .db import delete_user, get_db
from .form_security import attempt_budget
from .models import Contact, User, Work
from .privacy.models import PrivacyRequest
from .social.models import Report
from .security import admin_required, valid_session_identity
from .validation import storable_text

bp = Blueprint('admin',__name__)


@bp.get('/admin')
@admin_required
def index():
    db = get_db()
    stats = {
        'active_works': db.execute(select(func.count()).select_from(Work).where(Work.active == 1)).fetchone()[0],
        'archived_works': db.execute(select(func.count()).select_from(Work).where(Work.active == 0)).fetchone()[0],
        'users': db.execute(select(func.count()).select_from(User)).fetchone()[0],
        'reports': db.execute(select(func.count()).select_from(Report).where(Report.status == 'pending')).fetchone()[0],
        'contacts': db.execute(select(func.count()).select_from(Contact)).fetchone()[0],
        'privacy_requests': db.execute(select(func.count()).select_from(PrivacyRequest)
            .where(PrivacyRequest.status.in_(('received', 'in_review')))).fetchone()[0],
    }
    return render_template('admin/index.html', stats=stats)


@bp.get('/listar_users')
@admin_required
def listar_users():
    users = get_db().execute(select(User.id,User.username,User.nome,User.email).order_by(User.username)).fetchall()
    return render_template('admin_users.html',users=users)


@bp.get('/listar_mensagens')
@admin_required
def listar_mensagens():
    return render_template('admin_mensagens.html',mensagens=get_db().execute(select(Contact).order_by(Contact.id.desc())).fetchall())


@bp.route('/admin_excluir',methods=['GET','POST'])
@admin_required
def admin_excluir():
    if request.method == 'POST':
        retry = attempt_budget('settings_security')
        if retry:
            flash('Muitas tentativas. Aguarde alguns minutos e tente novamente.', 'error')
            return render_template('admin_excluir.html'), 429, {'Retry-After': str(retry)}
        identity = request.form.get('username', '')
        password = request.form.get('senha', '')
        candidate = find_identity(identity.strip()) if storable_text(identity) and 1 <= len(identity) <= 254 else None
        db = get_db()
        identities = sorted({g.user['id'], *([candidate['id']] if candidate else [])})
        with db:
            # Follow the same ascending user-lock order as social/chat actions.
            # On SQLite a no-op UPDATE serializes the entire writer transaction.
            if db.dialect == 'sqlite':
                locked = db.execute(update(User).where(User.id.in_(identities))
                    .values(session_version=User.session_version).returning(*User.__table__.columns)).fetchall()
            else:
                locked = db.execute(select(User).where(User.id.in_(identities))
                    .order_by(User.id).with_for_update()).fetchall()
            current = {user['id']: user for user in locked}
            administrator = current.get(g.user['id'])
            if not valid_session_identity(administrator, session):
                session.clear()
                flash('Sua sessão expirou. Entre novamente para continuar.', 'error')
                return redirect(url_for('auth.index'))
            if administrator['admin'] != 1:
                abort(403)
            target = current.get(candidate['id']) if candidate else None
            credentials_valid = storable_text(password) and 1 <= len(password) <= 1024 and check_password_hash(administrator['senha'], password)
            identity_matches = target and identity.strip().lower() in (target['username'].lower(), target['email'].lower())
            if not credentials_valid or not identity_matches:
                flash('Usuário ou senha do administrador inválidos.', 'error')
            elif target['admin'] == 1:
                flash('Contas de administradores não podem ser excluídas por este formulário.', 'error')
            else:
                # delete_user commits this transaction only after its DELETEs.
                # All authorization checks and database erasure share the locks.
                cleanup = delete_user(target['id'])
                flash('Usuário, suas publicações e suas mensagens enviadas excluídos.', 'success')
                if cleanup['failed']:
                    flash('Há imagens com remoção pendente no armazenamento. A equipe precisa concluir a limpeza.', 'info')
                return redirect(url_for('admin.admin_excluir'))
    return render_template('admin_excluir.html')
