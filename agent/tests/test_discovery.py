"""Discovery tests with mocked Places API (respx)."""
import httpx
import respx

from fmaj_agent.discovery import discover
from fmaj_agent.places import BASE, PlacesClient


def _place(pid: str, name: str, lat: float, lng: float, types=None, country="AU"):
    place = {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": f"{name} St, Sydney NSW",
        "location": {"latitude": lat, "longitude": lng},
        "types": types or ["restaurant"],
    }
    if country is not None:
        place["addressComponents"] = [
            {"longText": "New South Wales", "shortText": "NSW",
             "types": ["administrative_area_level_1", "political"]},
            {"longText": country, "shortText": country,
             "types": ["country", "political"]},
        ]
    return place


SYD = (-33.8688, 151.2093)


@respx.mock
def test_discover_dedupes_filters_and_fetches_details() -> None:
    nearby = respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    _place("a", "Cafe Near", SYD[0] + 0.001, SYD[1]),
                    _place("a", "Cafe Near", SYD[0] + 0.001, SYD[1]),  # dup
                    _place("b", "Cafe Far", SYD[0] + 0.5, SYD[1]),  # ~55km away
                ]
            },
        )
    )
    details = respx.get(f"{BASE}/places/a").mock(
        return_value=httpx.Response(200, json={"id": "a", "websiteUri": "https://cafenear.au"})
    )

    client = PlacesClient(api_key="test-key")
    result = discover(*SYD, radius_km=5, roles=["chef"], client=client)

    assert nearby.called
    assert details.called
    names = [c.name for c in result.companies]
    assert names == ["Cafe Near"]  # dedup + radius filter dropped the rest
    assert result.companies[0].website == "https://cafenear.au"
    assert result.stats["details_calls"] == 1
    assert result.stats["raw_candidates"] == 2


@respx.mock
def test_nearby_is_called_once_per_type_not_once_per_role() -> None:
    """Nearby (New) returns max 20 with no pagination, so bundling every type
    into one call caps the ENTIRE search at 20 candidates.

    That is what happened in Melbourne CBD at 5km: one call, 20 raw candidates,
    against a MAX_COMPANIES of 40. This test pins the shape so the ceiling can't
    silently come back — assert on the call count, not just the result.
    """
    from fmaj_agent import mapping

    types = mapping.resolve("kitchen hand").types
    assert len(types) > 1, "fixture assumes a multi-type role"

    seen: list[list[str]] = []

    def _respond(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        seen.append(body["includedTypes"])
        # 20 per call, the real API's ceiling, all unique across calls
        i = len(seen)
        return httpx.Response(200, json={"places": [
            _place(f"p{i}-{n}", f"Place {i}-{n}", SYD[0] + n * 0.0001, SYD[1])
            for n in range(20)
        ]})

    nearby = respx.post(f"{BASE}/places:searchNearby").mock(side_effect=_respond)
    respx.get(url__regex=rf"{BASE}/places/.*").mock(
        return_value=httpx.Response(200, json={"websiteUri": "https://x.au"})
    )

    result = discover(*SYD, radius_km=5, roles=["kitchen hand"],
                      client=PlacesClient(api_key="test-key"), fetch_details=False)

    assert nearby.call_count == len(types)
    assert all(len(t) == 1 for t in seen), f"types were bundled: {seen}"
    # The whole point: the candidate pool is no longer stuck at one page of 20.
    assert result.stats["raw_candidates"] == 20 * len(types)


@respx.mock
def test_unknown_role_uses_text_search_only() -> None:
    text = respx.post(f"{BASE}/places:searchText").mock(
        return_value=httpx.Response(
            200, json={"places": [_place("x", "Flower Shop", SYD[0], SYD[1])]}
        )
    )
    client = PlacesClient(api_key="test-key")
    result = discover(*SYD, radius_km=5, roles=["florist"], client=client, fetch_details=False)

    assert text.called
    assert client.stats.nearby_calls == 0
    assert [c.name for c in result.companies] == ["Flower Shop"]
    assert result.companies[0].website is None


@respx.mock
def test_details_failure_does_not_kill_discovery() -> None:
    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(200, json={"places": [_place("a", "Cafe", *SYD)]})
    )
    respx.post(f"{BASE}/places:searchText").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/places/a").mock(return_value=httpx.Response(500))

    client = PlacesClient(api_key="test-key")
    result = discover(*SYD, radius_km=5, roles=["chef"], client=client)
    assert len(result.companies) == 1
    assert result.companies[0].website is None


@respx.mock
def test_country_comes_from_the_places_result() -> None:
    """The agent picks its job board from this, so it must be the real country.

    The app is no longer Australia-only; a London search has to reach the
    per-company agent tagged `gb`, not defaulted to `au`.
    """
    london = (51.5074, -0.1278)
    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(
            200,
            json={"places": [_place("a", "Cafe UK", *london, country="GB")]},
        )
    )
    respx.post(f"{BASE}/places:searchText").mock(return_value=httpx.Response(200, json={}))

    result = discover(*london, radius_km=5, roles=["chef"],
                      client=PlacesClient(api_key="test-key"), fetch_details=False)

    assert result.companies[0].country_code == "gb"
    assert result.stats["country"] == "gb"


@respx.mock
def test_place_without_a_country_borrows_the_search_majority() -> None:
    """A place missing the component still gets the search's country, not None —
    but only because its neighbours agree, never because AU is the default."""
    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(
            200,
            json={"places": [
                _place("a", "Cafe A", SYD[0] + 0.0001, SYD[1], country="AU"),
                _place("b", "Cafe B", SYD[0] + 0.0002, SYD[1], country="AU"),
                _place("c", "Cafe C", SYD[0] + 0.0003, SYD[1], country=None),
            ]},
        )
    )
    respx.post(f"{BASE}/places:searchText").mock(return_value=httpx.Response(200, json={}))

    result = discover(*SYD, radius_km=5, roles=["chef"],
                      client=PlacesClient(api_key="test-key"), fetch_details=False)

    assert {c.country_code for c in result.companies} == {"au"}


@respx.mock
def test_country_is_unknown_when_places_never_says() -> None:
    """No country anywhere -> None, and the tools skip the regional boards."""
    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(
            200, json={"places": [_place("a", "Cafe", *SYD, country=None)]}
        )
    )
    respx.post(f"{BASE}/places:searchText").mock(return_value=httpx.Response(200, json={}))

    result = discover(*SYD, radius_km=5, roles=["chef"],
                      client=PlacesClient(api_key="test-key"), fetch_details=False)

    assert result.companies[0].country_code is None
    assert result.stats["country"] == "unknown"


@respx.mock
def test_cap_at_max_companies() -> None:
    many = [
        _place(f"p{i}", f"Cafe {i}", SYD[0] + i * 0.0001, SYD[1]) for i in range(30)
    ]
    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(200, json={"places": many})
    )
    client = PlacesClient(api_key="test-key")
    result = discover(
        *SYD, radius_km=5, roles=["chef"], client=client, max_companies=10, fetch_details=False
    )
    assert len(result.companies) == 10
    # closest first
    assert result.companies[0].name == "Cafe 0"


@respx.mock
def test_a_text_only_role_is_not_stuck_at_one_page() -> None:
    """The ceiling behind "MAX_COMPANIES=40 but I only ever get 20".

    A role with no Places types — `it support`, or any label not in
    role_mapping.yaml, which is every office role — reaches the API through Text
    Search alone. Both endpoints cap at 20 per request, but only Text Search
    paginates, so without following nextPageToken the search was capped at 20
    candidates no matter what MAX_COMPANIES said.
    """
    page1 = [_place(f"a{i}", f"IT Co {i}", SYD[0] + i * 0.0001, SYD[1]) for i in range(20)]
    page2 = [_place(f"b{i}", f"Dev Co {i}", SYD[0] + i * 0.0001, SYD[1]) for i in range(20)]
    responses = [
        httpx.Response(200, json={"places": page1, "nextPageToken": "tok-2"}),
        httpx.Response(200, json={"places": page2}),  # no token -> last page
    ]
    seen_tokens = []

    def _handler(request):
        import json as _json
        seen_tokens.append(_json.loads(request.content).get("pageToken"))
        return responses[len(seen_tokens) - 1]

    respx.post(f"{BASE}/places:searchText").mock(side_effect=_handler)
    client = PlacesClient(api_key="test-key")
    result = discover(*SYD, radius_km=5, roles=["florist"], client=client,
                      max_companies=40, fetch_details=False)

    assert seen_tokens == [None, "tok-2"]        # the token was followed
    assert client.stats.text_calls == 2          # …and each page is one billed call
    assert result.stats["raw_candidates"] == 40  # not 20


@respx.mock
def test_a_role_with_types_does_not_pay_for_extra_text_pages() -> None:
    """Nearby already gives 20 per type, so text search stays on one page."""
    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(200, json={"places": [
            _place("n1", "Site Co", SYD[0], SYD[1])]})
    )
    text = respx.post(f"{BASE}/places:searchText").mock(
        return_value=httpx.Response(
            200, json={"places": [_place("t1", "Builder", SYD[0], SYD[1])],
                       "nextPageToken": "tok-2"}  # offered, deliberately not taken
        )
    )
    client = PlacesClient(api_key="test-key")
    discover(*SYD, radius_km=5, roles=["construction labourer"], client=client,
             max_companies=40, fetch_details=False)

    assert text.call_count == 1
    assert client.stats.text_calls == 1


@respx.mock
def test_text_pagination_stops_when_google_runs_out() -> None:
    """A short tail must not cost three calls."""
    respx.post(f"{BASE}/places:searchText").mock(
        return_value=httpx.Response(200, json={"places": [
            _place("t1", "Only One", SYD[0], SYD[1])]})   # no nextPageToken
    )
    client = PlacesClient(api_key="test-key")
    result = discover(*SYD, radius_km=5, roles=["florist"], client=client,
                      max_companies=40, fetch_details=False)
    assert client.stats.text_calls == 1
    assert len(result.companies) == 1


@respx.mock
def test_several_phrasings_share_the_page_budget() -> None:
    """An office role is described, not typed, so one phrase is not the pool.

    Three phrasings one page deep beat one phrasing three pages deep: the deeper
    pages are the same query's long tail, while a different phrasing finds
    companies the first one never described. So the pages-per-query drop as the
    queries multiply, and the call count stays bounded.
    """
    calls = []

    def _handler(request):
        import json as _json
        body = _json.loads(request.content)
        calls.append((body["textQuery"], body.get("pageToken")))
        return httpx.Response(200, json={"places": [
            _place(f"p{len(calls)}", f"Co {len(calls)}", SYD[0], SYD[1])]})

    respx.post(f"{BASE}/places:searchText").mock(side_effect=_handler)
    client = PlacesClient(api_key="test-key")
    discover(*SYD, radius_km=5, roles=["it support"], client=client,
             max_companies=40, fetch_details=False)

    # two phrasings x 20 per page already covers max_companies -> one page each
    assert [q for q, _ in calls] == ["IT services company",
                                     "managed IT services provider"]
    assert all(token is None for _, token in calls)


@respx.mock
def test_every_company_says_which_call_found_it() -> None:
    """Provenance, because "we ran three queries" is not evidence any of their
    results survived the cut. Melbourne CBD x software developer ran two Nearby
    types and three text queries, and 39 of 40 shortlist places came from the
    types — distance ranking had crowded the text results out entirely. Without
    a source column that is invisible."""
    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(200, json={"places": [
            _place("n1", "Near Cafe", SYD[0], SYD[1], types=["cafe"])]})
    )
    respx.post(f"{BASE}/places:searchText").mock(
        return_value=httpx.Response(200, json={"places": [
            _place("t1", "Far Builder", SYD[0] + 0.01, SYD[1])]})
    )
    client = PlacesClient(api_key="test-key")
    result = discover(*SYD, radius_km=5, roles=["construction labourer"],
                      client=client, fetch_details=False)

    by_name = {c.name: c.discovery_source for c in result.companies}
    assert by_name["Near Cafe"].startswith("nearby:")
    assert by_name["Far Builder"] == "text:construction company"
    assert result.stats["by_source"]["text:construction company"] == 1
