from fmaj_agent import mapping


def test_curated_role_resolves_types() -> None:
    plan = mapping.resolve("Chef")
    assert plan.curated
    assert "restaurant" in plan.types


def test_unknown_role_falls_back_to_text_search() -> None:
    plan = mapping.resolve("florist")
    assert not plan.curated
    assert plan.types == ()
    assert plan.text_query == "florist"


def test_text_only_roles() -> None:
    plan = mapping.resolve("aged care worker")
    assert plan.curated
    assert plan.types == ()
    assert plan.text_query == "aged care facility"


def test_all_curated_roles_have_a_source() -> None:
    for role in mapping.curated_roles():
        plan = mapping.resolve(role)
        assert plan.types or plan.text_query, f"{role} has neither types nor text_query"
