"""Engine configuration, explicit migrations and shared database commands."""
import sqlite3
from pathlib import Path

import click
from alembic import command
from alembic.config import Config
from flask import current_app
from sqlalchemy import create_engine, delete, event, insert, or_, select, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool, StaticPool
from werkzeug.security import generate_password_hash

from .config import ROOT
from .models import Card, User
from .persistence import close_db, get_db, get_engine
from .validation import email_valido, senha_forte, username_valido


def upgrade_database(app=None, *, keep_duplicate_review='latest'):
    if keep_duplicate_review not in {'latest', 'oldest'}:
        raise ValueError('Use latest or oldest for historical duplicate reviews')
    application = app or current_app
    config = Config()
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    config.attributes['keep_duplicate_review'] = keep_duplicate_review
    with application.extensions['database_engine'].begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config,'heads')


def init_db():
    upgrade_database()


def ensure_admin():
    username = current_app.config['ADM_USERNAME'].strip().upper()
    password = current_app.config['ADM_SENHA']
    if not username or not password:
        return
    db = get_db()
    if db.execute(select(User.id).where(User.admin == 1)).fetchone():
        return
    email = current_app.config['ADM_EMAIL'].strip().lower()
    if not username_valido(username) or not senha_forte(password) or not email_valido(email):
        raise ValueError('Credenciais ADM inválidas. Confira a configuração de ambiente.')
    try:
        with db:
            db.execute(insert(User).values(username=username,nome='Administrador',apelido='Admin',
                       about='Administração do Criti-CARD',email=email,senha=generate_password_hash(password),
                       admin=1,search_name='administrador'))
    except IntegrityError as error:
        raise ValueError('Username ou email ADM já pertence a uma conta existente.') from error


def delete_user(user_id):
    from .chat.models import Message
    from .chat.service import handle_user_deletion
    from .communities.models import (Community, CommunityComment, CommunityMembership, CommunityPost)
    from .social.models import Notification, Report
    from .privacy.cleanup import cleanup_images, queue_image
    db = get_db()
    with db:
        # Lock the owner before clearing dependent text. Concurrent sends and
        # account actions must finish before deletion or see the deleted owner.
        user = db.execute(update(User).where(User.id == user_id)
            .values(session_version=User.session_version).returning(User.imagem)).fetchone()
        covers = db.execute(select(Card.capa).where(Card.author_id == user_id)).fetchall()
        handle_user_deletion(db,user_id)
        # Transfer owner role before account cascades remove its memberships.
        owned_communities = db.execute(select(Community.id).join(CommunityMembership,
            CommunityMembership.community_id == Community.id).where(
                CommunityMembership.user_id == user_id, CommunityMembership.role == 'owner')).fetchall()
        for owned in owned_communities:
            successor = db.execute(select(CommunityMembership.__table__).join(User,
                User.id == CommunityMembership.user_id).where(
                CommunityMembership.community_id == owned['id'], CommunityMembership.user_id != user_id,
                User.active == 1)
                .order_by((CommunityMembership.role == 'moderator').desc(),
                    CommunityMembership.joined_at, CommunityMembership.user_id).limit(1)).fetchone()
            if successor:
                db.execute(update(CommunityMembership).where(
                    CommunityMembership.community_id == owned['id'],
                    CommunityMembership.user_id == successor['user_id']).values(role='owner'))
            else:
                old_cover = db.execute(select(Community.cover).where(Community.id == owned['id'])).scalar()
                db.execute(update(Community).where(Community.id == owned['id']).values(
                    archived=1, cover=None))
                if old_cover:
                    queue_image('cover', old_cover)
        # The creator identity is personal metadata; community ownership lives
        # in the membership role and can survive transfer to another member.
        db.execute(update(Community).where(Community.created_by == user_id).values(created_by=None))
        authored_posts = select(CommunityPost.id).where(CommunityPost.author_id == user_id)
        authored_comments = select(CommunityComment.id).where(or_(
            CommunityComment.author_id == user_id,
            CommunityComment.post_id.in_(authored_posts)))
        db.execute(delete(Report).where(Report.target_type == 'community_post', Report.target_id.in_(authored_posts)))
        db.execute(delete(Report).where(Report.target_type == 'community_comment', Report.target_id.in_(authored_comments)))
        db.execute(delete(CommunityComment).where(CommunityComment.author_id == user_id))
        db.execute(delete(CommunityPost).where(CommunityPost.author_id == user_id))
        authored_messages = select(Message.id).where(Message.sender_id==user_id)
        db.execute(delete(Report).where(Report.target_type=='chat_message',Report.target_id.in_(authored_messages)))
        # A NULL sender is not anonymization of free-text personal information.
        # Delete only this account's messages; preserve the other participant's.
        db.execute(delete(Message).where(Message.sender_id == user_id))
        db.execute(delete(Report).where(Report.reporter_id == user_id))
        db.execute(delete(Notification).where(Notification.actor_id == user_id))
        db.execute(delete(Card).where(Card.author_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        if user:
            queue_image('avatar', user['imagem'])
        for filename in {card['capa'] for card in covers}:
            queue_image('cover', filename)
    # Failed storage work stays in an operational queue, never in the account.
    return cleanup_images()


def init_app(app):
    configured = app.config.get('DATABASE_URL')
    if configured:
        url = make_url(configured)
        if url.drivername in ('postgres','postgresql'):
            url = url.set(drivername='postgresql+psycopg')
    else:
        url = URL.create('sqlite',database=app.config['DATABASE'])
    if url.get_backend_name() not in ('sqlite','postgresql'):
        raise ValueError('Use SQLite local ou PostgreSQL na configuração do banco.')
    options = {'pool_pre_ping':True}
    if url.get_backend_name() == 'sqlite':
        options.update(poolclass=NullPool,connect_args={'timeout':10})
        if not url.database or url.database == ':memory:':
            options.update(poolclass=StaticPool,connect_args={'timeout':10,'check_same_thread':False})
        if url.database and url.database != ':memory:':
            Path(url.database).parent.mkdir(parents=True,exist_ok=True)
    engine = create_engine(url,**options)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine,'connect')
        def sqlite_options(connection,record):
            connection.execute('PRAGMA foreign_keys = ON')
            connection.create_function('casefold',1,lambda value: str(value or '').casefold(),deterministic=True)
    app.extensions['database_engine'] = engine
    app.teardown_appcontext(close_db)

    @app.cli.command('db-upgrade')
    def upgrade_command():
        upgrade_database()
        ensure_admin()
        click.echo('Migrações aplicadas; dados existentes preservados.')

    @app.cli.command('init-db')
    def initialize_command():
        upgrade_database()
        ensure_admin()
        click.echo('Migrações aplicadas; dados existentes preservados.')

    @app.cli.command('db-backup')
    @click.argument('destination',type=click.Path(path_type=Path))
    def backup_command(destination):
        if engine.dialect.name != 'sqlite':
            raise click.ClickException('Para PostgreSQL use pg_dump e verifique a restauração.')
        if destination.exists():
            raise click.ClickException('O arquivo de destino já existe.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(engine.url.database) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        click.echo('Backup SQLite consistente criado.')
