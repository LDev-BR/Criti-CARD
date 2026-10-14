"""Personal dashboard and profile administration."""
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from .db import delete_user, get_db
from .models import Card, Contact, User
from .queries import get_author_cards
from .security import login_required, valid_session_identity
from .form_security import attempt_budget
from .uploads import remove_image, save_image
from .validation import profile_values, storable_text, validate_profile

bp = Blueprint('profiles',__name__)


def render_dashboard(support_text=''):
    from .social.service import card_social_state
    from .progression.queries import journey_summary, public_styles
    archived = request.args.get('aba') == 'arquivados'
    cards = get_author_cards(g.user['id'], archived=archived)
    counts = {row['archived']: row['total'] for row in get_db().execute(select(Card.archived,
        func.count().label('total')).where(Card.author_id == g.user['id']).group_by(Card.archived)).fetchall()}
    return render_template('dashboard.html',usuario=g.user,card=cards,support_text=support_text,
                           summary=journey_summary(g.user['id']),profile_style=public_styles([g.user['id']])[g.user['id']],
                           showing_archived=archived, published_count=counts.get(0, 0), archived_count=counts.get(1, 0),
                           social_states=card_social_state([c['id'] for c in cards],g.user['id']))


@bp.get('/dashboard')
@login_required
def dashboard():
    return render_dashboard()


@bp.route('/edit',methods=['GET','POST'])
@login_required
def edit():
    values = profile_values(request.form) if request.method == 'POST' else dict(g.user)
    if request.method == 'POST':
        filename = None
        try:
            from .privacy.cleanup import cleanup_images, queue_image
            validate_profile(values, existing_email=g.user['email'])
            db = get_db()
            if db.execute(select(User.id).where(User.id != g.user['id'],or_(func.lower(User.username) == values['username'].lower(),func.lower(User.email) == values['email'].lower()))).fetchone():
                raise ValueError('Username ou email já cadastrado.')
            filename = save_image(request.files.get('imagem'),current_app.config['UPLOAD_FOLDER'])
            with db:
                # Read the prior image under the owner lock. Two simultaneous
                # replacements must retire the image actually replaced, rather
                # than the snapshot loaded at the start of each request.
                current = db.execute(update(User).where(User.id == g.user['id'], User.active == 1)
                    .values(session_version=User.session_version).returning(*User.__table__.columns)).fetchone()
                if not valid_session_identity(current, session):
                    remove_image(current_app.config['UPLOAD_FOLDER'], filename)
                    session.clear()
                    flash('Sua sessão expirou. Entre novamente para continuar.', 'error')
                    return redirect(url_for('auth.index'))
                email_changed = values['email'].lower() != current['email'].lower()
                db.execute(update(User).where(User.id == current['id']).values(**values,imagem=filename or current['imagem'],
                           search_name=values['nome'].casefold(),email_verified=0 if email_changed else current['email_verified']))
                if filename and filename != current['imagem']:
                    queue_image('avatar', current['imagem'])
                if email_changed:
                    from .accounts.service import invalidate_email_links
                    invalidate_email_links(g.user['id'])
            if filename:
                cleanup = cleanup_images()
                if cleanup['failed']:
                    flash('Há imagens antigas com remoção pendente no armazenamento. A equipe precisa concluir a limpeza.', 'info')
            if email_changed:
                from .accounts.service import send_verification
                send_verification(g.user['id'], request.remote_addr)
            flash('Perfil atualizado.','success')
            return redirect(url_for('profiles.dashboard'))
        except (ValueError,IntegrityError) as error:
            remove_image(current_app.config['UPLOAD_FOLDER'],filename)
            flash(str(error) if isinstance(error,ValueError) else 'Username ou email já cadastrado.','error')
    return render_template('edit.html',usuario=g.user,values=values)


@bp.route('/excluir_user',methods=['GET','POST'])
@bp.route('/delete',methods=['GET','POST'])
@login_required
def excluir():
    if request.method == 'POST':
        retry = attempt_budget('settings_security')
        if retry:
            response = current_app.make_response(render_template('excluir.html', user=g.user,
                delete_error='Muitas tentativas. Aguarde alguns minutos e tente novamente.'))
            response.status_code = 429
            response.headers['Retry-After'] = str(retry)
            return response
        password = request.form.get('senha',request.form.get('dlsn',''))
        db = get_db()
        with db:
            current = db.execute(update(User).where(User.id == g.user['id'], User.active == 1)
                .values(session_version=User.session_version).returning(*User.__table__.columns)).fetchone()
            if not valid_session_identity(current, session):
                session.clear()
                flash('Sua sessão expirou. Entre novamente para continuar.', 'error')
                return redirect(url_for('auth.index'))
            verified = storable_text(password) and 1 <= len(password) <= 1024 and check_password_hash(current['senha'],password)
            if verified:
                cleanup = delete_user(current['id'])
        if verified:
            session.clear()
            flash('Sua conta, suas publicações e suas mensagens enviadas foram excluídas.','success')
            if cleanup['failed']:
                flash('Há imagens com remoção pendente no armazenamento. A equipe precisa concluir a limpeza.', 'info')
            return redirect(url_for('auth.index'))
        flash('Senha inválida. Confirme a senha da sua conta.','error')
    return render_template('excluir.html',user=g.user)


@bp.route('/mensagem',methods=['GET','POST'])
@login_required
def mensagem():
    if request.method == 'POST':
        text = request.form.get('mensagem','').strip()
        if storable_text(text) and 1 <= len(text) <= 2000:
            db = get_db()
            with db:
                db.execute(insert(Contact).values(user_id=g.user['id'],nome=g.user['username'],email=g.user['email'],mensagem=text))
            flash('Mensagem enviada à equipe.','success')
        else:
            flash('Escreva uma mensagem de 1 a 2000 caracteres.','error')
            return render_dashboard(request.form.get('mensagem',''))
    return redirect(url_for('profiles.dashboard'))
