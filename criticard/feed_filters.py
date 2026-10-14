"""Normalize feed filters once before building SQL or navigation URLs."""
from dataclasses import dataclass
from .validation import storable_text

SORTS = {
    "recent": ("Mais recentes", "c.id DESC"),
    "popular": ("Mais comentadas", "popular"),
    "highest": ("Maiores notas", "c.nota DESC, c.id DESC"),
    "lowest": ("Menores notas", "c.nota ASC, c.id DESC"),
    "oldest": ("Mais antigos", "c.id ASC"),
}


@dataclass(frozen=True)
class FeedFilters:
    query: str = ""
    category: str = ""
    work: int | None = None
    minimum: int = 0
    sort: str = "recent"
    feed: str = "community"
    ignore_preferences: bool = False

    def url_args(self, **changes):
        args = {"q": self.query, "categoria": self.category, "obra": self.work,
                "nota_min": self.minimum or None, "ordem": self.sort if self.sort != "recent" else None,
                "feed": self.feed if self.feed == 'following' else None,
                "preferencias": 'ignorar' if self.ignore_preferences else None}
        args.update(changes)
        return {key: value for key, value in args.items() if value not in (None, "")}

    @property
    def active(self):
        return bool(self.query or self.category or self.work or self.minimum or self.sort != "recent")


def normalized_filters(args, catalog):
    categories = {category["slug"]: category for category in catalog}
    works = {work["id"]: category["slug"] for category in catalog for work in category["works"]}
    category = args.get("categoria", "")
    if category not in categories:
        category = ""
    try:
        work = int(args.get("obra", ""))
    except (TypeError, ValueError):
        work = None
    if work not in works or (category and works[work] != category):
        work = None
    elif not category:
        category = works[work]
    try:
        minimum = min(100, max(0, int(args.get("nota_min", "0"))))
    except (TypeError, ValueError):
        minimum = 0
    sort = args.get("ordem", "recent")
    query = args.get('q', '')
    return FeedFilters(query.strip()[:120] if storable_text(query) else '', category, work, minimum,
                       sort if sort in SORTS else "recent", 'following' if args.get('feed') == 'following' else 'community')
