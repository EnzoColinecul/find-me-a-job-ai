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
