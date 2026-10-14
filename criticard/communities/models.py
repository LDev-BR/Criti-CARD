"""Thematic communities, membership and their independent publication walls."""
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import mapped_column

from ..models import Base, ID, utcnow


class Community(Base):
    __tablename__ = 'communities'
    __table_args__ = (
        UniqueConstraint('slug', name='uq_communities_slug'),
        UniqueConstraint('category_id', name='uq_communities_category'),
        CheckConstraint("mode IN ('open','closed')", name='ck_communities_mode'),
        CheckConstraint('minimum_level >= 1', name='ck_communities_minimum_level'),
        CheckConstraint('seeded IN (0,1)', name='ck_communities_seeded'),
        CheckConstraint('archived IN (0,1)', name='ck_communities_archived'),
        Index('ix_communities_discovery', 'archived', 'seeded', 'created_at'))
    id = mapped_column(ID, primary_key=True)
    category_id = mapped_column(ID, ForeignKey('categorias.id', ondelete='SET NULL'))
    slug = mapped_column(String(100), nullable=False)
    name = mapped_column(String(80), nullable=False)
    description = mapped_column(String(1000), nullable=False, default='', server_default='')
    theme = mapped_column(String(24), nullable=False, default='gold', server_default='gold')
    icon = mapped_column(String(32), nullable=False, default='sparkles', server_default='sparkles')
    cover = mapped_column(String(255))
    mode = mapped_column(String(16), nullable=False, default='open', server_default='open')
    minimum_level = mapped_column(Integer, nullable=False, default=1, server_default='1')
    created_by = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    seeded = mapped_column(Integer, nullable=False, default=0, server_default='0')
    archived = mapped_column(Integer, nullable=False, default=0, server_default='0')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CommunityMembership(Base):
    __tablename__ = 'community_memberships'
    __table_args__ = (
        CheckConstraint("role IN ('owner','moderator','member')", name='ck_community_memberships_role'),
        Index('ix_community_memberships_user', 'user_id', 'community_id'),
        Index('ix_community_memberships_community', 'community_id', 'joined_at'))
    community_id = mapped_column(ID, ForeignKey('communities.id', ondelete='CASCADE'), primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True)
    role = mapped_column(String(16), nullable=False, default='member', server_default='member')
    joined_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CommunityJoinRequest(Base):
    __tablename__ = 'community_join_requests'
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','denied','cancelled')", name='ck_community_join_requests_status'),
        Index('uq_community_join_requests_pending', 'community_id', 'user_id', unique=True,
            sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
        Index('ix_community_join_requests_community_status', 'community_id', 'status', 'created_at'),
        {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    community_id = mapped_column(ID, ForeignKey('communities.id', ondelete='CASCADE'), nullable=False)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    status = mapped_column(String(16), nullable=False, default='pending', server_default='pending')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = mapped_column(DateTime(timezone=True))
    resolved_by = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))


class CommunityInvite(Base):
    __tablename__ = 'community_invites'
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','cancelled')", name='ck_community_invites_status'),
        Index('uq_community_invites_pending', 'community_id', 'invitee_id', unique=True,
            sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
        Index('ix_community_invites_invitee_status', 'invitee_id', 'status', 'created_at'),
        {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    community_id = mapped_column(ID, ForeignKey('communities.id', ondelete='CASCADE'), nullable=False)
    inviter_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    invitee_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    status = mapped_column(String(16), nullable=False, default='pending', server_default='pending')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = mapped_column(DateTime(timezone=True))


class CommunityPost(Base):
    __tablename__ = 'community_posts'
    __table_args__ = (
        CheckConstraint('length(title) BETWEEN 1 AND 120', name='ck_community_posts_title_length'),
        CheckConstraint('length(body) BETWEEN 1 AND 5000', name='ck_community_posts_body_length'),
        Index('ix_community_posts_community_created', 'community_id', 'created_at'),
        Index('ix_community_posts_author', 'author_id', 'created_at'),
        {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    community_id = mapped_column(ID, ForeignKey('communities.id', ondelete='CASCADE'), nullable=False)
    author_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    work_id = mapped_column(ID, ForeignKey('obras.id', ondelete='SET NULL'))
    title = mapped_column(String(120), nullable=False)
    body = mapped_column(Text, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CommunityComment(Base):
    __tablename__ = 'community_comments'
    __table_args__ = (
        CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_community_comments_body_length'),
        Index('ix_community_comments_post_created', 'post_id', 'created_at'),
        Index('ix_community_comments_author', 'author_id', 'created_at'),
        {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    post_id = mapped_column(ID, ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False)
    author_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    body = mapped_column(Text, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CommunityReaction(Base):
    __tablename__ = 'community_reactions'
    __table_args__ = (
        UniqueConstraint('user_id', 'post_id', 'kind', name='uq_community_reactions_user_post_kind'),
        CheckConstraint("kind IN ('like','insightful','fun')", name='ck_community_reactions_kind'),
        Index('ix_community_reactions_post', 'post_id'))
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    post_id = mapped_column(ID, ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False)
    kind = mapped_column(String(16), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
