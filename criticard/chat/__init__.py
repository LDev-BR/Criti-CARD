"""Chat blueprint and the application's Socket.IO extension."""
from . import models
from .sockets import init_app, socketio
from .views import bp

__all__ = ['bp', 'init_app', 'socketio']
