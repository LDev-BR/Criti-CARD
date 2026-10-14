"""Welcome-first discovery home."""
from flask import Blueprint, g, render_template

from .service import hub_context

bp = Blueprint('discovery', __name__)


@bp.get('/feed')
def index():
    context = hub_context(g.user['id'] if g.user else None)
    return render_template('discovery/index.html', **context)
