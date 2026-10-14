"""Allowlisted original catalog illustrations, kept separate from user uploads."""

_TITLES = {
    "jogos": ("Elden Ring", "Hollow Knight", "Red Dead Redemption 2", "Hades", "The Last of Us Part I"),
    "filmes": ("Interestelar", "O Poderoso Chefão", "Matrix", "Parasita", "O Senhor dos Anéis: A Sociedade do Anel"),
    "series": ("Breaking Bad", "Dark", "Game of Thrones", "The Last of Us", "Sherlock"),
    "livros": ("1984", "Duna", "O Pequeno Príncipe", "Dom Casmurro", "O Senhor dos Anéis"),
    "animes": ("Attack on Titan", "Fullmetal Alchemist: Brotherhood", "Death Note", "One Piece", "Neon Genesis Evangelion"),
    "mangas": ("Berserk", "Vagabond", "Monster", "Vinland Saga", "Chainsaw Man"),
}


def _entry(slug, index, title):
    return {
        "marker": f"catalog:{slug}:{index}",
        "filename": f"catalog/{slug}-atlas.png",
        "columns": 3, "rows": 2, "column": index % 3, "row": index // 3,
        "label": f"Ilustração temática de {title}", "title": title, "category_slug": slug,
    }


_ART = {f"catalog:{slug}:{index}": _entry(slug, index, title)
        for slug, titles in _TITLES.items() for index, title in enumerate(titles)}
_BY_WORK = {(art["category_slug"], art["title"].casefold()): marker for marker, art in _ART.items()}


def art_for_marker(marker):
    """Resolve only known marker strings, never arbitrary filenames or URLs."""
    art = _ART.get(marker) if isinstance(marker, str) else None
    return dict(art) if art is not None else None


def art_for_work(work, category_slug=None):
    """Find seed artwork by title and category while preserving custom covers."""
    if work is None:
        return None
    # Query rows and dictionaries both expose mapping access.
    values = dict(work)
    cover = values.get("capa")
    if cover and cover != "default-cover.svg":
        return art_for_marker(cover)
    title = values.get("titulo")
    slug = category_slug or values.get("category_slug") or values.get("categoria_slug")
    if not isinstance(title, str) or not isinstance(slug, str):
        return None
    return art_for_marker(_BY_WORK.get((slug, title.casefold())))


def static_cover_name(filename):
    """Resolve only existing public image files within this app's static tree."""
    from pathlib import Path
    from flask import current_app
    if not isinstance(filename, str) or not filename or len(filename) > 230 or any(char in filename for char in ('\\', ':')):
        return None
    if any(ord(char) < 32 for char in filename):
        return None
    static = Path(current_app.static_folder).resolve()
    for candidate in (filename, 'cards/' + filename):
        path = (static / candidate).resolve()
        if (path.is_relative_to(static) and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'}
                and path.is_file()):
            return path.relative_to(static).as_posix()
    return None


def default_cover_for_work(work):
    """Return the stored cover source shared by catalog works and linked cards."""
    from pathlib import Path
    from flask import current_app
    from .storage import valid_image_name
    if work is None:
        return 'default-cover.svg'
    values = dict(work)
    art = art_for_work(values)
    if art:
        return art['marker']
    cover = values.get('capa')
    if not isinstance(cover, str) or not cover or cover == 'default-cover.svg':
        return 'default-cover.svg'
    if cover.startswith('catalog-static:'):
        public = static_cover_name(cover.removeprefix('catalog-static:'))
        return 'catalog-static:' + public if public else 'default-cover.svg'
    if valid_image_name(cover) and (Path(current_app.config['CAPA_FOLDER']) / cover).is_file():
        return cover
    public = static_cover_name(cover)
    if public:
        return 'catalog-static:' + public
    return cover if valid_image_name(cover) else 'default-cover.svg'


def cover_metadata_for_work(work):
    """Resolve safe public URLs, including uploaded local or S3 catalog covers."""
    from pathlib import Path
    from flask import current_app
    from .storage import image_url
    source = default_cover_for_work(work)
    art = art_for_marker(source)
    if art and not (Path(current_app.static_folder) / art['filename']).is_file():
        source, art = 'default-cover.svg', None
    return {'cover_source': source, 'cover_url': image_url('cover', source), 'cover_art': art}
