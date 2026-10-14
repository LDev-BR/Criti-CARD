"""Registration and cookie authentication backed by portable SQLAlchemy models."""
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .form_security import attempt_budget
from .models import User, utcnow
from .progression.service import lock_owner, sync_user, claim_notice
from .progression.types import ProgressionError
from .progression.presentation import announce
from .navigation import safe_local_path
from .security import session_identity
from .uploads import remove_image, save_image
from .validation import FormValidationError, profile_values, senha_forte, storable_text, validate_profile

bp = Blueprint('auth',__name__)
_DUMMY_HASH = generate_password_hash('unavailable-account-placeholder')


def find_identity(identity):
    if not storable_text(identity):
        return None
    return get_db().execute(select(User).where(or_(func.lower(User.username) == identity.lower(),
                                                 func.lower(User.email) == identity.lower()))).fetchone()


@bp.route('/',methods=['GET','POST'])
def index():
    login_error = None
    destination = safe_local_path(request.form.get('next', request.args.get('next')))
    if request.method == 'GET' and g.user is not None:
        return redirect(destination or url_for('profiles.dashboard'))
    if request.method == 'POST':
        retry = attempt_budget('login')
        if retry:
            return render_template('index.html',login_error='Muitas tentativas. Aguarde alguns minutos para tentar novamente.',next_path=destination),429,{'Retry-After':str(retry)}
        identity = request.form.get('username','').strip()
        password = request.form.get('senha','')
        user = find_identity(identity) if len(identity) <= 254 and len(password) <= 1024 else None
        valid = check_password_hash(user['senha'] if user else _DUMMY_HASH,password) if len(password) <= 1024 else False
        if user and valid and user['active']:
            try:
                with get_db() as db:
                    current = lock_owner(db,user['id'])
                    if current['senha'] != user['senha']:
                        raise ProgressionError('A identidade mudou durante o login.',401)
                    sync_user(db,current['id'],utcnow())
                    notice = claim_notice(db,current['id'],utcnow())
                session.clear()
                session['usuario_id'] = current['id']
                session['session_version'] = current['session_version']
                session['auth_stamp'] = session_identity(current)
                announce(notice)
                return redirect(destination or url_for('profiles.dashboard'))
            except ProgressionError:
                pass
        login_error = 'Usuário ou senha inválidos. Confira os dados e tente novamente.'
    return render_template('index.html',login_error=login_error,next_path=destination)


@bp.route('/cadastro',methods=['GET','POST'])
def cadastro():
    values = profile_values(request.form)
    field_errors = {}
    destination = safe_local_path(request.form.get('next', request.args.get('next')))
    if request.method == 'POST':
        retry = attempt_budget('register')
        if retry:
            return render_template('cadastro.html',values=values,destination=destination,field_errors={'email':'Muitas tentativas de cadastro. Aguarde alguns minutos e tente novamente.'}),429,{'Retry-After':str(retry)}
        filename = None
        try:
            validate_profile(values)
            password = request.form.get('senha','')
            if not senha_forte(password):
                raise FormValidationError('senha','Use 8 a 128 caracteres, com maiúscula, minúscula, número e !@#$%&_*.')
            db = get_db()
            for field,label in (('username','Username'),('email','Email')):
                if db.execute(select(User.id).where(func.lower(getattr(User,field)) == values[field].lower())).fetchone():
                    raise FormValidationError(field,f'{label} já cadastrado.')
            filename = save_image(request.files.get('imagem'),current_app.config['UPLOAD_FOLDER'])
            with db:
                user_id = db.execute(insert(User).values(**values,senha=generate_password_hash(password),imagem=filename,
                                               search_name=values['nome'].casefold()).returning(User.id)).scalar()
                sync_user(db,user_id,utcnow())
            from .accounts.mail import configured
            if configured():
                from .accounts.service import send_verification
                send_verification(user_id, request.remote_addr)
            flash('Conta criada! Faça login para publicar suas críticas.','success')
            return redirect(url_for('auth.index', **({'next': destination} if destination else {})))
        except (ValueError,IntegrityError) as error:
            remove_image(current_app.config['UPLOAD_FOLDER'],filename)
            field = getattr(error,'field','imagem') if isinstance(error,ValueError) else 'username'
            field_errors[field] = str(error) if isinstance(error,ValueError) else 'Username ou email já cadastrado.'
    return render_template('cadastro.html',values=values,field_errors=field_errors,destination=destination)


@bp.post('/logout')
def logout():
    if g.user:
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == g.user['id']).values(session_version=User.session_version + 1))
    session.clear()
    return redirect(url_for('auth.index'))
