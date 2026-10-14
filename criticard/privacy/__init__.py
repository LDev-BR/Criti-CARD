"""Public transparency and authenticated, private data-rights requests."""
from .views import bp


def init_app(app):
    from .cleanup import init_app as init_cleanup
    init_cleanup(app)
