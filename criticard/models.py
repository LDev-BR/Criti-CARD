"""Shared declarative models; feature modules define their own related tables."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


ID = BigInteger().with_variant(Integer, 'sqlite')


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'usuarios'
    __table_args__ = {'sqlite_autoincrement': True}
    id = mapped_column(ID, primary_key=True)
    username = mapped_column(Text, unique=True, nullable=False)
    nome = mapped_column(Text, nullable=False)
    apelido = mapped_column(Text, nullable=False)
    imagem = mapped_column(Text)
    about = mapped_column(Text, nullable=False)
    email = mapped_column(Text, unique=True, nullable=False)
    email_verified = mapped_column(Integer, nullable=False, server_default='0')
    senha = mapped_column(Text, nullable=False)
    admin = mapped_column(Integer, nullable=False, server_default='0')
    active = mapped_column(Integer, nullable=False, server_default='1')
    session_version = mapped_column(Integer, nullable=False, server_default='0')
    search_name = mapped_column(Text)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)


class Category(Base):
    __tablename__ = 'categorias'
    id = mapped_column(ID, primary_key=True)
    slug = mapped_column(Text, unique=True, nullable=False)
    nome = mapped_column(Text, nullable=False)


class Work(Base):
    __tablename__ = 'obras'
    __table_args__ = (CheckConstraint('active IN (0,1)', name='ck_obras_active'),)
    id = mapped_column(ID, primary_key=True)
    categoria_id = mapped_column(ID, ForeignKey('categorias.id'), nullable=False, index=True)
    titulo = mapped_column(Text, nullable=False)
    capa = mapped_column(Text)
    search_title = mapped_column(Text)
    active = mapped_column(Integer, nullable=False, server_default='1', index=True)
    created_at = mapped_column(DateTime(timezone=True))


class Card(Base):
    __tablename__ = 'cards'
    __table_args__ = (CheckConstraint('nota BETWEEN 0 AND 100', name='ck_cards_note_range'),
                     CheckConstraint('archived IN (0,1)', name='ck_cards_archived'),
                     Index('uq_cards_author_work_published', 'author_id', 'obra_id', unique=True,
                           sqlite_where=text('archived = 0'), postgresql_where=text('archived = 0')),
                     {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    titulo = mapped_column(Text, nullable=False)
    capa = mapped_column(Text, nullable=False)
    sobre = mapped_column(Text, nullable=False)
    nota = mapped_column(Integer, nullable=False)
    author_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    obra_id = mapped_column(ID, ForeignKey('obras.id'), index=True)
    archived = mapped_column(Integer, nullable=False, server_default='0')
    search_title = mapped_column(Text)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow)


class Contact(Base):
    __tablename__ = 'contatos'
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), index=True)
    nome = mapped_column(Text, nullable=False)
    email = mapped_column(Text, nullable=False)
    mensagem = mapped_column(Text, nullable=False)


class FormAttempt(Base):
    __tablename__ = 'form_attempts'
    scope = mapped_column(String(32), primary_key=True)
    client_key = mapped_column(String(64), primary_key=True)
    attempts = mapped_column(Integer, nullable=False)
    expires = mapped_column(Float, nullable=False, index=True)
