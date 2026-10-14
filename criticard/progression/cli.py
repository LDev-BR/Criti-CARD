import click
from sqlalchemy import select

from ..models import User, utcnow
from ..persistence import get_db
from .history import import_user_history
from .types import ProgressionError


def register_cli(app):
    @app.cli.command('progression-import-history')
    @click.option('--dry-run',is_flag=True,help='Calcular sem gravar XP, concessões ou marcador.')
    @click.option('--user-id',type=click.IntRange(1,2**63-1))
    def import_history(dry_run,user_id):
        db = get_db()
        users = [user_id] if user_id else [row['id'] for row in db.execute(select(User.id).order_by(User.id)).fetchall()]
        total = 0
        for owner in users:
            try:
                with db:
                    result = import_user_history(db,owner,utcnow())
                    if dry_run:
                        db.rollback()
            except ProgressionError as error:
                raise click.ClickException(str(error)) from error
            total += result['xp']
            click.echo(f"Conta {owner}: {result['reviews']} críticas, {result['completed']} conclusões, {result['xp']} XP"+
                ('; inativa, ignorada' if result['skipped'] else ''))
        click.echo(f"{'Simulação sem alterações' if dry_run else 'Importação concluída'}: {total} XP.")
