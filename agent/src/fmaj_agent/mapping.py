"""Role → Places-type mapping loader."""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

_MAPPING_FILE = Path(__file__).parent / "data" / "role_mapping.yaml"


@dataclass(frozen=True)
class RolePlan:
    role: str
    types: tuple[str, ...] = ()
    text_query: str | None = None
    curated: bool = True


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
        return RolePlan(role=key, types=(), text_query=key, curated=False)
    return RolePlan(
        role=key,
        types=tuple(entry.get("types") or ()),
        text_query=entry.get("text_query"),
        curated=True,
    )


def curated_roles() -> list[str]:
    return sorted(_load().keys())
