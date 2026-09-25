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


def test_text_queries_accepts_one_or_many() -> None:
    """`text_query: "x"` and `text_queries: [a, b]` are both valid in the YAML."""
    from fmaj_agent.mapping import _queries

    assert _queries({"text_query": "aged care facility"}) == ("aged care facility",)
    assert _queries({"text_queries": ["a", "b"]}) == ("a", "b")
    assert _queries({"text_queries": ["a", "A", " a "]}) == ("a",)  # deduped
    assert _queries({}) == ()


def test_text_query_still_reads_as_the_first_query() -> None:
    plan = mapping.resolve("software developer")
    assert plan.text_query == plan.text_queries[0]


def test_office_roles_have_something_to_search_with() -> None:
    """An office role has no Places venue type, so its phrasing IS the search."""
    for role in ("software developer", "it support"):
        plan = mapping.resolve(role)
        assert plan.curated, f"{role} fell through to the raw-label fallback"
        assert plan.text_queries, f"{role} has no query to run"
