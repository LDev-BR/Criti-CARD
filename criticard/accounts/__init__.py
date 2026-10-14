"""Account link lifecycle and private outbound email spool."""
from .models import AccountToken
from .views import bp

__all__ = ["AccountToken", "bp"]
