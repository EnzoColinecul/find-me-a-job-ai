"""Google Places API (New) client.

Cost discipline (see docs/PLAN.md §2.3):
- search_nearby / search_text request ONLY Pro-tier fields (no websiteUri!).
- place_details requests Enterprise fields (websiteUri, phone) — only 1K free
  calls/month, so callers must restrict it to the shortlisted companies.
Call counts are tracked so every search can log its Places usage.
"""

from dataclasses import dataclass, field

import httpx

from fmaj_agent import config, secrets

BASE = "https://places.googleapis.com/v1"


class PlacesError(RuntimeError):
    """Places API error that includes the response body (Google explains 403s there)."""


def _check(resp: httpx.Response) -> httpx.Response:
    if not resp.is_error:
        return resp

    body = resp.text
    # The single most likely 403 here, and the raw Google payload buries it under
    # 500 characters of JSON. There are two Places keys — a referrer-restricted
    # browser one and an unrestricted server one — and putting the browser key
    # where the server expects one fails exactly like this.
    if "API_KEY_HTTP_REFERRER_BLOCKED" in body:
        raise PlacesError(
            "Places rejected the key: it is HTTP-referrer restricted, so it only "
            "works from a browser. The pipeline needs the SERVER key (no "
            "application restriction, Places API (New) only). Whatever supplied "
            f"the key — FMAJ_PLACES_KEY, or the secret `{config.PLACES_KEY_SECRET}` "
            "— currently holds the browser key from web/.env.local. Fix with "
            "scripts/store-external-secrets.sh (blank prompts keep their value)."
        )
    if "API_KEY_SERVICE_BLOCKED" in body or "SERVICE_DISABLED" in body:
        raise PlacesError(
            "Places rejected the key: Places API (New) is not enabled for it, or "
            f"the key's API restrictions exclude it. Body: {body[:300]}"
        )
    raise PlacesError(f"{resp.status_code} {resp.request.url}: {body[:500]}")


# Pro tier — safe for discovery volume (5K free/mo).
#
# `addressComponents` is ALSO Pro, so asking for it costs nothing extra, and it is
# the only place we get an exact ISO-3166 country code (`shortText` on the
# component typed `country`). The agent needs that to pick a job board that covers
# the search area instead of assuming Australia — see `discovery._country_code`.
# Don't move it into DETAILS_FIELD_MASK: Details is the Enterprise SKU.
SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location," "places.types,places.addressComponents"
)
# Enterprise tier — shortlist only (1K free/mo)
DETAILS_FIELD_MASK = "id,websiteUri,nationalPhoneNumber"

MAX_RADIUS_M = 50_000

#: Both Places search endpoints return at most 20 places per request — that is
#: Google's ceiling, not a setting of ours (`maxResultCount` is documented as
#: "between 1 and 20 (default)"). Raising it does nothing. Breadth comes from
#: making more requests: one Nearby call per type, and — since Text Search alone
#: supports `nextPageToken` — more than one page of text results.
PAGE_SIZE = 20


@dataclass
class PlacesStats:
    nearby_calls: int = 0
    text_calls: int = 0
    details_calls: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "nearby_calls": self.nearby_calls,
            "text_calls": self.text_calls,
            "details_calls": self.details_calls,
        }


@dataclass
class PlacesClient:
    api_key: str | None = None
    timeout: float = 10.0
    stats: PlacesStats = field(default_factory=PlacesStats)

    def _headers(self, field_mask: str) -> dict[str, str]:
        return {
            "X-Goog-Api-Key": self.api_key or secrets.places_api_key(),
            "X-Goog-FieldMask": field_mask,
            "Content-Type": "application/json",
        }

    def search_nearby(
        self, lat: float, lng: float, radius_m: float, included_types: list[str]
    ) -> list[dict]:
        """Nearby Search (New). Max 20 per request (Google's ceiling), no pagination.

        `maxResultCount` is documented as "between 1 and 20 (default)", so the 20
        below is not a tuning knob — raising it changes nothing. Breadth comes
        from `discovery` calling this once per place type.
        """
        self.stats.nearby_calls += 1
        body = {
            "includedTypes": included_types,
            "maxResultCount": 20,
            "rankPreference": "DISTANCE",  # closest first, not popularity
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": min(radius_m, MAX_RADIUS_M),
                }
            },
        }
        resp = httpx.post(
            f"{BASE}/places:searchNearby",
            json=body,
            headers=self._headers(SEARCH_FIELD_MASK),
            timeout=self.timeout,
        )
        return _check(resp).json().get("places", [])

    def search_text(
        self, query: str, lat: float, lng: float, radius_m: float, max_pages: int = 1
    ) -> list[dict]:
        """Text Search (New). Bias — results may fall outside radius.

        **Unlike Nearby, this one paginates.** `pageSize` maxes out at 20 per
        request for both endpoints, but Text Search returns a `nextPageToken`
        and Nearby has no pagination at all, so a text-only role was silently
        capped at 20 candidates however high `MAX_COMPANIES` was set — the same
        shape of bug as the bundled Nearby call, just on the other endpoint.
        Roles with no Places types (`it support`, anything uncurated) reach the
        API through here ONLY, so for them this cap *was* the search.

        Each page is a separate billed request, on the Pro SKU (5K/month free),
        so callers ask for the depth they need rather than paging blindly —
        see `discovery`, which only pages for roles Nearby can't serve.

        Google requires the rest of the request to be unchanged when a
        `pageToken` is sent, so the body is rebuilt identically each time.
        """
        places: list[dict] = []
        token: str | None = None
        for _ in range(max(1, max_pages)):
            self.stats.text_calls += 1
            body = {
                "textQuery": query,
                "pageSize": 20,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": min(radius_m, MAX_RADIUS_M),
                    }
                },
            }
            if token:
                body["pageToken"] = token
            resp = httpx.post(
                f"{BASE}/places:searchText",
                json=body,
                headers=self._headers(SEARCH_FIELD_MASK),
                timeout=self.timeout,
            )
            data = _check(resp).json()
            places.extend(data.get("places", []))
            token = data.get("nextPageToken")
            if not token:
                break
        return places

    def place_details(self, place_id: str) -> dict:
        """Enterprise-tier details (websiteUri, phone). SHORTLIST ONLY — 1K free/mo."""
        self.stats.details_calls += 1
        resp = httpx.get(
            f"{BASE}/places/{place_id}",
            headers=self._headers(DETAILS_FIELD_MASK),
            timeout=self.timeout,
        )
        return _check(resp).json()
