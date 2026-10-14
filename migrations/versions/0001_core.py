"""Baseline and non-destructive upgrade from the original Criti-CARD schema."""
from collections import defaultdict

from alembic import op
import sqlalchemy as sa

revision = '0001_core'
down_revision = None
branch_labels = None
depends_on = None

# Frozen data: future catalog additions must use a new revision or admin tools.
SEED = (
    ('jogos','Jogos',('Elden Ring','Hollow Knight','Red Dead Redemption 2','Hades','The Last of Us Part I')),
    ('filmes','Filmes',('Interestelar','O Poderoso Chefão','Matrix','Parasita','O Senhor dos Anéis: A Sociedade do Anel')),
    ('series','Séries',('Breaking Bad','Dark','Game of Thrones','The Last of Us','Sherlock')),
    ('livros','Livros',('1984','Duna','O Pequeno Príncipe','Dom Casmurro','O Senhor dos Anéis')),
    ('animes','Animes',('Attack on Titan','Fullmetal Alchemist: Brotherhood','Death Note','One Piece','Neon Genesis Evangelion')),
    ('mangas','Mangás',('Berserk','Vagabond','Monster','Vinland Saga','Chainsaw Man')),
)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    identity = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    def pk():
        return sa.Column('id', identity, primary_key=True)
    def column(name, nullable=False):
        return sa.Column(name, sa.Text(), nullable=nullable)
    if 'usuarios' not in existing:
        op.create_table('usuarios',pk(),column('username'),column('nome'),column('apelido'),column('imagem',True),
                        column('about'),column('email'),column('senha'),sa.Column('admin',sa.Integer(),server_default='0',nullable=False),
                        sa.UniqueConstraint('username'),sa.UniqueConstraint('email'),sqlite_autoincrement=True)
    if 'categorias' not in existing:
        op.create_table('categorias',pk(),column('slug'),column('nome'),sa.UniqueConstraint('slug'))
    if 'obras' not in existing:
        op.create_table('obras',pk(),sa.Column('categoria_id',identity,sa.ForeignKey('categorias.id'),nullable=False),
                        column('titulo'))
    if 'cards' not in existing:
        op.create_table('cards',pk(),column('titulo'),column('capa'),column('sobre'),sa.Column('nota',sa.Integer(),nullable=False),
                        sa.Column('author_id',identity,sa.ForeignKey('usuarios.id',ondelete='CASCADE'),nullable=False),
                        sa.CheckConstraint('nota BETWEEN 0 AND 100',name='ck_cards_note_range'),sqlite_autoincrement=True)
    elif 'card_id' in {c['name'] for c in sa.inspect(bind).get_columns('cards')}:
        op.alter_column('cards','card_id',new_column_name='author_id')
    if 'contatos' not in existing:
        op.create_table('contatos',pk(),column('nome'),column('email'),column('mensagem'))
    if 'form_attempts' not in existing:
        op.create_table('form_attempts',sa.Column('scope',sa.String(32),primary_key=True),
                        sa.Column('client_key',sa.String(64),primary_key=True),sa.Column('attempts',sa.Integer(),nullable=False),
                        sa.Column('expires',sa.Float(),nullable=False))
    additions = {
        'usuarios':[sa.Column('search_name',sa.Text()),sa.Column('created_at',sa.DateTime(timezone=True)),
                    sa.Column('active',sa.Integer(),server_default='1',nullable=False),
                    sa.Column('session_version',sa.Integer(),server_default='0',nullable=False)],
        'obras':[sa.Column('capa',sa.Text()),sa.Column('search_title',sa.Text())],
        'cards':[sa.Column('obra_id',identity,sa.ForeignKey('obras.id')),sa.Column('search_title',sa.Text()),
                 sa.Column('created_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True))],
    }
    for table, columns in additions.items():
        current = {c['name'] for c in sa.inspect(bind).get_columns(table)}
        for c in columns:
            if c.name not in current:
                # SQLite cannot ALTER ADD a foreign-key constraint. Its nullable
                # REFERENCES column is added directly and foreign_keys stays on.
                if table == 'cards' and c.name == 'obra_id' and bind.dialect.name == 'sqlite':
                    op.execute('ALTER TABLE cards ADD COLUMN obra_id INTEGER REFERENCES obras(id)')
                else:
                    op.add_column(table,c)
    meta = sa.MetaData()
    users = sa.Table('usuarios',meta,autoload_with=bind)
    cards = sa.Table('cards',meta,autoload_with=bind)
    categories = sa.Table('categorias',meta,autoload_with=bind)
    works = sa.Table('obras',meta,autoload_with=bind)
    for slug,name,titles in SEED:
        category_id = bind.execute(sa.select(categories.c.id).where(categories.c.slug == slug)).scalar()
        if category_id is None:
            category_id = bind.execute(categories.insert().values(slug=slug,nome=name).returning(categories.c.id)).scalar()
        for title in titles:
            if not bind.execute(sa.select(works.c.id).where(works.c.categoria_id == category_id,works.c.titulo == title)).scalar():
                bind.execute(works.insert().values(categoria_id=category_id,titulo=title,search_title=title.casefold()))
    matches = defaultdict(list)
    for row in bind.execute(sa.select(works.c.id,works.c.titulo)):
        matches[row.titulo.casefold()].append(row.id)
        bind.execute(works.update().where(works.c.id == row.id).values(search_title=row.titulo.casefold()))
    for row in bind.execute(sa.select(users.c.id,users.c.nome)):
        bind.execute(users.update().where(users.c.id == row.id).values(search_name=row.nome.casefold()))
    for row in bind.execute(sa.select(cards.c.id,cards.c.titulo,cards.c.obra_id)):
        values = {'search_title':row.titulo.casefold()}
        if row.obra_id is None and len(matches[row.titulo.casefold()]) == 1:
            values['obra_id'] = matches[row.titulo.casefold()][0]
        bind.execute(cards.update().where(cards.c.id == row.id).values(**values))
    for table, name, columns in (
        ('cards','idx_cards_author',['author_id','id']),('cards','idx_cards_work',['obra_id']),
        ('obras','ix_obras_categoria_id',['categoria_id']),('form_attempts','idx_form_attempts_expires',['expires'])):
        if name not in {index['name'] for index in sa.inspect(bind).get_indexes(table)}:
            op.create_index(name,table,columns)


def downgrade():
    raise RuntimeError('Baseline downgrade is destructive; restore a verified backup instead.')
