"""Version-skew safety: an older Lambda may receive RoleSpec dicts from a newer API."""
from fmaj_agent import mapping
from fmaj_agent.models import RoleSpec


def test_resolve_accepts_plain_string() -> None:
    assert "restaurant" in mapping.resolve("chef").types


def test_resolve_accepts_rolespec_dict() -> None:
    plan = mapping.resolve({"label": "dishwasher", "curated_key": "kitchen hand"})
    assert plan.curated and "restaurant" in plan.types


def test_resolve_accepts_rolespec_object() -> None:
    plan = mapping.resolve(RoleSpec(label="dishwasher", curated_key="kitchen hand"))
    assert "restaurant" in plan.types


def test_resolve_dict_without_curated_key_uses_label() -> None:
    plan = mapping.resolve({"label": "chef", "curated_key": None})
    assert "restaurant" in plan.types
