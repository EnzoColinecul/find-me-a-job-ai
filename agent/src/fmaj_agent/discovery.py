"""Company discovery: location + radius + roles -> deduped, capped candidate list.

Pipeline per search:
  1. For each role: Nearby Search per mapped type-group + optional Text Search.
  2. Merge, dedupe by place_id, filter to radius (text results can drift outside).
  3. Rank by distance, cap at MAX_COMPANIES.
  4. Place Details (Enterprise fields) for the capped list only -> websiteUri.
"""
import logging
import math
from dataclasses import dataclass, field

from fmaj_agent import mapping
from fmaj_agent.models import Company
from fmaj_agent.places import PlacesClient

logger = logging.getLogger(__name__)

MAX_COMPANIES = 40


@dataclass
class DiscoveryResult:
    companies: list[Company] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _to_candidate(place: dict, roles: list[str]) -> dict:
    return {
        "place_id": place["id"],
        "name": (place.get("displayName") or {}).get("text", ""),
        "address": place.get("formattedAddress", ""),
        "types": place.get("types", []),
        "lat": (place.get("location") or {}).get("latitude"),
        "lng": (place.get("location") or {}).get("longitude"),
        "roles": list(roles),
    }


def discover(
    lat: float,
    lng: float,
    radius_km: float,
    roles: list[str],
    client: PlacesClient | None = None,
    max_companies: int = MAX_COMPANIES,
    fetch_details: bool = True,
) -> DiscoveryResult:
    client = client or PlacesClient()
    radius_m = radius_km * 1000
    candidates: dict[str, dict] = {}

    for role in roles:
        plan = mapping.resolve(role)
        raw: list[dict] = []
        if plan.types:
            raw.extend(client.search_nearby(lat, lng, radius_m, list(plan.types)))
        if plan.text_query:
            raw.extend(client.search_text(plan.text_query, lat, lng, radius_m))
        for place in raw:
            cand = _to_candidate(place, roles)
            if cand["lat"] is None or not cand["name"]:
                continue
            existing = candidates.get(cand["place_id"])
            if existing is None:
                candidates[cand["place_id"]] = cand

    # radius filter (text search bias can drift) + distance ranking
    ranked = []
    for cand in candidates.values():
        dist = _haversine_km(lat, lng, cand["lat"], cand["lng"])
        if dist <= radius_km * 1.1:  # 10% tolerance on the edge
            cand["distance_km"] = round(dist, 2)
            ranked.append(cand)
    ranked.sort(key=lambda c: c["distance_km"])
    shortlist = ranked[:max_companies]

    # Enterprise details for shortlist ONLY (websiteUri)
    companies: list[Company] = []
    for cand in shortlist:
        website = None
        if fetch_details:
            try:
                details = client.place_details(cand["place_id"])
                website = details.get("websiteUri")
            except Exception as exc:  # noqa: BLE001 — details failure must not kill discovery
                logger.warning("details failed for %s: %s", cand["place_id"], exc)
        companies.append(
            Company(
                place_id=cand["place_id"],
                name=cand["name"],
                address=cand["address"],
                types=cand["types"],
                website=website,
                roles=cand["roles"],
            )
        )

    stats = {
        **client.stats.as_dict(),
        "raw_candidates": len(candidates),
        "within_radius": len(ranked),
        "shortlisted": len(companies),
        "with_website": sum(1 for c in companies if c.website),
    }
    logger.info("discovery stats: %s", stats)
    return DiscoveryResult(companies=companies, stats=stats)
