"""The published review of an author/work is the entry point for reevaluation."""
from sqlalchemy import select

from .db import get_db
from .models import Card
from .validation import FormValidationError


class DuplicateReview(FormValidationError):
    def __init__(self, card_id):
        super().__init__('obra_id', 'Você já tem um card desta obra. Edite sua crítica existente para reavaliá-la.')
        self.card_id = card_id


def existing_review(author_id, work_id, *, excluding=None):
    statement = select(Card.id).where(Card.author_id == author_id,
        Card.obra_id == work_id, Card.archived == 0)
    if excluding is not None:
        statement = statement.where(Card.id != excluding)
    return get_db().execute(statement.limit(1)).scalar()


def reviewed_works(author_id, *, excluding=None):
    statement = select(Card.obra_id, Card.id).where(Card.author_id == author_id,
        Card.obra_id.is_not(None), Card.archived == 0)
    if excluding is not None:
        statement = statement.where(Card.id != excluding)
    return {row['obra_id']: row['id'] for row in get_db().execute(statement).fetchall()}


def require_unique_review(author_id, work_id, *, excluding=None):
    card_id = existing_review(author_id, work_id, excluding=excluding)
    if card_id is not None:
        raise DuplicateReview(card_id)
