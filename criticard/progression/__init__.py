"""Progression feature; lazy views keep model registration cycle-free."""


def __getattr__(name):
    if name == 'bp':
        from .views import bp
        return bp
    raise AttributeError(name)
