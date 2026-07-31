"""Google Places API (New) client.

Cost discipline (see docs/PLAN.md §2.3):
- search_nearby / search_text request ONLY Pro-tier fields (no websiteUri!).
- place_details requests Enterprise fields (websiteUri, phone) — only 1K free
  calls/month, so callers must restrict it to the shortlisted companies.
Call counts are tracked so every search can log its Places usage.
"""
from dataclasses import dataclass, field

import httpx

from fmaj_agent import secrets

BASE = "https://places.googleapis.com/v1"

# Pro tier — safe for discovery volume (5K free/mo)
SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,places.types"
)
# Enterprise tier — shortlist only (1K free/mo)
DETAILS_FIELD_MASK = "id,websiteUri,nationalPhoneNumber"

MAX_RADIUS_M = 50_000


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
        """Nearby Search (New). Max 20 results per request, no pagination."""
        self.stats.nearby_calls += 1
        body = {
            "includedTypes": included_types,
            "maxResultCount": 20,
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
        resp.raise_for_status()
        return resp.json().get("places", [])

    def search_text(self, query: str, lat: float, lng: float, radius_m: float) -> list[dict]:
        """Text Search (New), single page (20). Bias — results may fall outside radius."""
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
        resp = httpx.post(
            f"{BASE}/places:searchText",
            json=body,
            headers=self._headers(SEARCH_FIELD_MASK),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("places", [])

    def place_details(self, place_id: str) -> dict:
        """Enterprise-tier details (websiteUri, phone). SHORTLIST ONLY — 1K free/mo."""
        self.stats.details_calls += 1
        resp = httpx.get(
            f"{BASE}/places/{place_id}",
            headers=self._headers(DETAILS_FIELD_MASK),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
