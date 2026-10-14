"""Small shared context for the application navigation and footer."""
from datetime import datetime, timezone
from flask import g

from .db import get_db
from .models import Category
from sqlalchemy import select


def init_app(app):
    @app.before_request
    def load_preferences():
        from .settings.schema import DEFAULTS
        from .settings.service import get_preferences
        g.preferences = get_preferences(g.user['id']) if g.user else dict(DEFAULTS)

    @app.context_processor
    def shell_context():
        from .social.service import unread_count
        from .social.connections import incoming_request_count
        from .accounts.mail import configured
        from .settings.schema import DEFAULTS
        return {"current_year": datetime.now(timezone.utc).year,
                "ui_preferences": getattr(g, 'preferences', DEFAULTS),
                "account_mail_enabled": configured(),
                "notification_unread_count": unread_count(g.user['id']) if g.user else 0,
                "friend_request_count": incoming_request_count(g.user['id']) if g.user else 0,
                "navigation_categories": get_db().execute(select(Category.slug, Category.nome).order_by(Category.id)).fetchall()}
