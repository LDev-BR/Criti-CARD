"""Bounded local return paths for authentication journeys."""
from urllib.parse import unquote, urlsplit


def safe_local_path(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or not value.startswith('/'):
        return None
    decoded = value
    for _ in range(4):
        if any(ord(char) < 32 or ord(char) == 127 for char in decoded) or '\\' in decoded:
            return None
        try:
            parsed = urlsplit(decoded)
        except ValueError:
            return None
        if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith('/') or parsed.path.startswith('//'):
            return None
        if parsed.path == '/':
            return None
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    return value
