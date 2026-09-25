"""Role → Places-type mapping loader."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_MAPPING_FILE = Path(__file__).parent / "data" / "role_mapping.yaml"


@dataclass(frozen=True)
class RolePlan:
    role: str
    types: tuple[str, ...] = ()
    #: Text Search queries for this role. A LIST, because one phrase cannot
    #: describe an office employer the way a Places type describes a cafe:
    #: "software development company", "web development agency" and "software
    #: company" surface overlapping but different sets, and the union is the
    #: candidate pool. Venue-typed roles usually need none of this.
    text_queries: tuple[str, ...] = ()
    curated: bool = True

    @property
    def text_query(self) -> str | None:
        """The first query. Kept so existing callers and tests still read."""
        return self.text_queries[0] if self.text_queries else None


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    with open(_MAPPING_FILE) as f:
        return yaml.safe_load(f)


def resolve(role) -> RolePlan:
    """Return the discovery plan for a role. Unknown roles -> Text Search fallback.

    Accepts a plain string or a RoleSpec-shaped dict: during a rolling deploy the API
    may already send {"label": ..., "curated_key": ...} while an older Lambda is live.
    """
    if isinstance(role, dict):
        role = role.get("curated_key") or role.get("label") or ""
    elif hasattr(role, "mapping_key"):
        role = role.mapping_key
    key = str(role).strip().lower()
    entry = _load().get(key)
    if entry is None:
        return RolePlan(role=key, types=(), text_queries=(key,), curated=False)
    return RolePlan(
        role=key,
        types=tuple(entry.get("types") or ()),
        text_queries=_queries(entry),
        curated=True,
    )


def _queries(entry: dict) -> tuple[str, ...]:
    """`text_query: "one"` and `text_queries: [a, b]` are both accepted.

    The singular form is what most of the file uses and there is no reason to
    churn it; the plural exists for roles where one phrase isn't enough.
    """
    raw = entry.get("text_queries") or entry.get("text_query") or ()
    if isinstance(raw, str):
        raw = [raw]
    seen, out = set(), []
    for q in raw:
        q = " ".join(str(q).split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return tuple(out)


def curated_roles() -> list[str]:
    return sorted(_load().keys())
