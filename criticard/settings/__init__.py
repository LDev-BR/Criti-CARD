"""Account settings blueprint, loaded lazily during application registration."""


def __getattr__(name):
    if name == 'bp':
        from .views import bp
        return bp
    raise AttributeError(name)
