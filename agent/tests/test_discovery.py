"""Discovery tests with mocked Places API (respx)."""
import httpx
import respx

from fmaj_agent.discovery import discover
from fmaj_agent.places import BASE, PlacesClient


def _place(pid: str, name: str, lat: float, lng: float, types=None):
    return {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": f"{name} St, Sydney NSW",
        "location": {"latitude": lat, "longitude": lng},
        "types": types or ["restaurant"],
    }


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
