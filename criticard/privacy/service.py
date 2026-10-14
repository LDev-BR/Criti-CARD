"""Ownership, bounded input and atomic request/reply operations."""
import re
import secrets

from flask import g, session
from sqlalchemy import func, insert, select, update

from criticard.db import get_db
from criticard.models import User, utcnow
from criticard.security import valid_session_identity
from criticard.validation import storable_text
from .models import PrivacyReply, PrivacyRequest

KINDS = {'access': 'Confirmação e acesso', 'correction': 'Correção de dados',
    'deletion': 'Anonimização, bloqueio ou eliminação', 'portability': 'Portabilidade',
    'sharing': 'Informações sobre compartilhamento', 'consent': 'Informações ou revogação de consentimento',
    'objection': 'Oposição ou revisão de decisão automatizada', 'other': 'Outro direito ou dúvida'}
STATUSES = {'received': 'Recebido', 'in_review': 'Em análise', 'answered': 'Respondido'}
PAGE_SIZE = 20


class PrivacyError(ValueError):
    def __init__(self, message, field=None, status=422, retry=0):
        super().__init__(message)
        self.field, self.status, self.retry = field, status, retry


def checked_text(value):
    if not storable_text(value) or not 1 <= len(value) <= 3000 or not value.strip():
        raise PrivacyError('Escreva de 1 a 3000 caracteres, sem incluir senhas ou documentos.', 'body')
    return value.strip()


def _lock_identity(admin=False):
    db = get_db()
    user = db.execute(update(User).where(User.id == g.user['id'], User.active == 1)
        .values(session_version=User.session_version).returning(*User.__table__.columns)).fetchone()
    if not valid_session_identity(user, session):
        raise PrivacyError('Sua sessão expirou. Entre novamente.', status=401)
    if admin and user['admin'] != 1:
        raise PrivacyError('Você não tem permissão para atender pedidos.', status=403)
    return user


def create_request(kind, body):
    if not isinstance(kind, str) or kind not in KINDS:
        raise PrivacyError('Escolha o assunto do pedido.', 'kind')
    body = checked_text(body)
    db = get_db()
    with db:
        owner = _lock_identity()
        now = utcnow()
        record = db.execute(insert(PrivacyRequest).values(user_id=owner['id'], kind=kind,
            body=body, protocol='CC-' + secrets.token_hex(16), created_at=now, updated_at=now)
            .returning(*PrivacyRequest.__table__.columns)).fetchone()
    return record


def get_request(protocol, *, admin=False):
    if not isinstance(protocol, str) or not re.fullmatch(r'CC-[0-9a-f]{32}', protocol):
        raise PrivacyError('Pedido não encontrado.', status=404)
    conditions = [PrivacyRequest.protocol == protocol]
    if not admin:
        conditions.append(PrivacyRequest.user_id == g.user['id'])
    record = get_db().execute(select(PrivacyRequest).where(*conditions)).fetchone()
    if record is None:
        raise PrivacyError('Pedido não encontrado.', status=404)
    return record


def reply_to_request(protocol, status, body):
    if not isinstance(status, str) or status not in STATUSES:
        raise PrivacyError('Escolha um status válido.', 'status')
    body = checked_text(body)
    db = get_db()
    with db:
        administrator = _lock_identity(admin=True)
        record = get_request(protocol, admin=True)
        # Serializes concurrent replies so status and ordered history agree.
        locked = db.execute(update(PrivacyRequest).where(PrivacyRequest.id == record['id'])
            .values(updated_at=PrivacyRequest.updated_at).returning(PrivacyRequest.id)).scalar()
        if locked is None:
            raise PrivacyError('Pedido não encontrado.', status=404)
        now = utcnow()
        db.execute(insert(PrivacyReply).values(request_id=locked, responder_id=administrator['id'],
            body=body, status=status, created_at=now))
        db.execute(update(PrivacyRequest).where(PrivacyRequest.id == locked).values(status=status, updated_at=now))
    return get_request(protocol, admin=True)


def _timestamp(value):
    return value.isoformat() if value else None


def serialize(record, *, detail=False, admin=False):
    item = {key: record[key] for key in ('protocol', 'kind', 'status')}
    item.update(kind_label=KINDS[record['kind']], status_label=STATUSES[record['status']],
        created_at=_timestamp(record['created_at']), updated_at=_timestamp(record['updated_at']))
    if detail:
        item['body'] = record['body']
        replies = get_db().execute(select(PrivacyReply.body, PrivacyReply.status, PrivacyReply.created_at)
            .where(PrivacyReply.request_id == record['id']).order_by(PrivacyReply.id)).fetchall()
        item['replies'] = [dict(reply, status_label=STATUSES[reply['status']],
            created_at=_timestamp(reply['created_at'])) for reply in replies]
    if admin:
        owner = get_db().execute(select(User.username, User.email).where(User.id == record['user_id'])).fetchone()
        item['owner'] = dict(owner) if owner else None
    return item


def request_list(page=1, *, admin=False, status=''):
    page = int(page) if isinstance(page, str) and len(page) <= 7 and page.isdecimal() else 1
    conditions = [] if admin else [PrivacyRequest.user_id == g.user['id']]
    status = status if isinstance(status, str) and status in STATUSES else ''
    if status:
        conditions.append(PrivacyRequest.status == status)
    db = get_db()
    total = db.execute(select(func.count()).select_from(PrivacyRequest).where(*conditions)).scalar()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    records = db.execute(select(PrivacyRequest).where(*conditions).order_by(PrivacyRequest.id.desc())
        .limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).fetchall()
    return {'requests': [serialize(record, admin=admin) for record in records],
        'total': total, 'page': page, 'pages': pages, 'status': status}


def export_requests(owner_id):
    records = get_db().execute(select(PrivacyRequest).where(PrivacyRequest.user_id == owner_id)
        .order_by(PrivacyRequest.id)).fetchall()
    return [serialize(record, detail=True) for record in records]
