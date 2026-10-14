"""Add thematic communities, publication walls and membership workflows."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0015_thematic_communities'
down_revision = '0014_group_chats'
branch_labels = None
depends_on = None


def upgrade():
    identifier = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    op.create_table('communities',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('category_id', identifier, sa.ForeignKey('categorias.id', ondelete='SET NULL')),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('description', sa.String(1000), nullable=False, server_default=''),
        sa.Column('theme', sa.String(24), nullable=False, server_default='gold'),
        sa.Column('icon', sa.String(32), nullable=False, server_default='sparkles'),
        sa.Column('cover', sa.String(255)),
        sa.Column('mode', sa.String(16), nullable=False, server_default='open'),
        sa.Column('minimum_level', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', identifier, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.Column('seeded', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('archived', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('slug', name='uq_communities_slug'),
        sa.UniqueConstraint('category_id', name='uq_communities_category'),
        sa.CheckConstraint("mode IN ('open','closed')", name='ck_communities_mode'),
        sa.CheckConstraint('minimum_level >= 1', name='ck_communities_minimum_level'),
        sa.CheckConstraint('seeded IN (0,1)', name='ck_communities_seeded'),
        sa.CheckConstraint('archived IN (0,1)', name='ck_communities_archived'))
    op.create_index('ix_communities_discovery', 'communities', ['archived','seeded','created_at'])
    op.create_table('community_memberships',
        sa.Column('community_id', identifier, sa.ForeignKey('communities.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role', sa.String(16), nullable=False, server_default='member'),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner','moderator','member')", name='ck_community_memberships_role'))
    op.create_index('ix_community_memberships_user', 'community_memberships', ['user_id','community_id'])
    op.create_index('ix_community_memberships_community', 'community_memberships', ['community_id','joined_at'])
    op.create_table('community_join_requests',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('community_id', identifier, sa.ForeignKey('communities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_by', identifier, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.CheckConstraint("status IN ('pending','approved','denied','cancelled')", name='ck_community_join_requests_status'),
        sqlite_autoincrement=True)
    op.create_index('uq_community_join_requests_pending', 'community_join_requests', ['community_id','user_id'],
        unique=True, sqlite_where=sa.text("status = 'pending'"), postgresql_where=sa.text("status = 'pending'"))
    op.create_index('ix_community_join_requests_community_status', 'community_join_requests',
        ['community_id','status','created_at'])
    op.create_table('community_invites',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('community_id', identifier, sa.ForeignKey('communities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('inviter_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('invitee_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending','accepted','declined','cancelled')", name='ck_community_invites_status'),
        sqlite_autoincrement=True)
    op.create_index('uq_community_invites_pending', 'community_invites', ['community_id','invitee_id'],
        unique=True, sqlite_where=sa.text("status = 'pending'"), postgresql_where=sa.text("status = 'pending'"))
    op.create_index('ix_community_invites_invitee_status', 'community_invites', ['invitee_id','status','created_at'])
    op.create_table('community_posts',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('community_id', identifier, sa.ForeignKey('communities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('work_id', identifier, sa.ForeignKey('obras.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(120), nullable=False), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(title) BETWEEN 1 AND 120', name='ck_community_posts_title_length'),
        sa.CheckConstraint('length(body) BETWEEN 1 AND 5000', name='ck_community_posts_body_length'),
        sqlite_autoincrement=True)
    op.create_index('ix_community_posts_community_created','community_posts',['community_id','created_at'])
    op.create_index('ix_community_posts_author','community_posts',['author_id','created_at'])
    op.create_table('community_comments',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('post_id', identifier, sa.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_community_comments_body_length'),
        sqlite_autoincrement=True)
    op.create_index('ix_community_comments_post_created','community_comments',['post_id','created_at'])
    op.create_index('ix_community_comments_author','community_comments',['author_id','created_at'])
    op.create_table('community_reactions',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('user_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('post_id', identifier, sa.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id','post_id','kind',name='uq_community_reactions_user_post_kind'),
        sa.CheckConstraint("kind IN ('like','insightful','fun')",name='ck_community_reactions_kind'))
    op.create_index('ix_community_reactions_post','community_reactions',['post_id'])

    with op.batch_alter_table('reports') as batch:
        batch.drop_constraint('ck_reports_target_type', type_='check')
        batch.alter_column('target_type', existing_type=sa.String(16), type_=sa.String(24), nullable=False)
        batch.create_check_constraint('ck_reports_target_type',
            "target_type IN ('card','comment','user','chat_message','community_post','community_comment')")

    # One stable category-backed community per existing catalog category.
    connection = op.get_bind()
    categories = connection.execute(sa.text('SELECT id, slug, nome FROM categorias ORDER BY id')).fetchall()
    now = datetime.now(timezone.utc)
    for category in categories:
        category_slug = str(category.slug).strip().lower()
        slug = ('tema-' + category_slug)[:100]
        icon = {'jogos':'game', 'filmes':'film', 'series':'film', 'livros':'book',
            'animes':'film', 'mangas':'book'}.get(category_slug, 'sparkles')
        theme = {'jogos':'violet', 'filmes':'rose', 'series':'blue', 'livros':'green',
            'animes':'gold', 'mangas':'dark'}.get(category_slug, 'gold')
        connection.execute(sa.text(
            "INSERT INTO communities(category_id,slug,name,description,theme,icon,mode,minimum_level,seeded,archived,created_at,updated_at) "
            "SELECT :category_id,:slug,:name,:description,:theme,:icon,'open',1,1,0,:now,:now WHERE NOT EXISTS "
            "(SELECT 1 FROM communities WHERE category_id=:category_id OR slug=:slug)"),
            {'category_id':category.id,'slug':slug,'name':str(category.nome)[:80],
                'description':f"Comunidade temática de {category.nome} para críticas e conversas.",
                'theme':theme,'icon':icon,'now':now})


def downgrade():
    with op.batch_alter_table('reports') as batch:
        batch.drop_constraint('ck_reports_target_type', type_='check')
        batch.alter_column('target_type', existing_type=sa.String(24), type_=sa.String(16), nullable=False)
        batch.create_check_constraint('ck_reports_target_type',
            "target_type IN ('card','comment','user','chat_message')")
    op.drop_table('community_reactions')
    op.drop_table('community_comments')
    op.drop_table('community_posts')
    op.drop_table('community_invites')
    op.drop_table('community_join_requests')
    op.drop_table('community_memberships')
    op.drop_index('ix_communities_discovery', table_name='communities')
    op.drop_table('communities')
