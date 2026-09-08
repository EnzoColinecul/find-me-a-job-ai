"""Company discovery: location + radius + roles -> deduped, capped candidate list.

Pipeline per search:
  1. For each role: one Nearby Search PER mapped type (see the note at the call
     site — Nearby caps at 20 per request with no pagination, so bundling the
     types into one call caps the whole search at 20) + optional Text Search.
  2. Merge, dedupe by place_id, filter to radius (text results can drift outside).
  3. Rank by distance, cap at MAX_COMPANIES.
  4. Place Details (Enterprise fields) for the capped list only -> websiteUri.
"""

import logging
import math
from collections import Counter
from dataclasses import dataclass, field

from fmaj_agent import config, mapping
from fmaj_agent.models import Company, RoleSpec
from fmaj_agent import places as places_mod
from fmaj_agent.places import PlacesClient

logger = logging.getLogger(__name__)

#: Ceiling regardless of configuration: Place Details is the Enterprise SKU
#: (1K/month) and one search must never be able to eat the monthly quota.
#: `FMAJ_MAX_COMPANIES=0` means "no PoC limit", not "no limit at all".
HARD_MAX_COMPANIES = 40

#: Text Search pages to pull for a role Nearby cannot serve. A role with no
#: Places types reaches the API through Text Search alone, and one page is 20
#: places — so `MAX_COMPANIES=40` was unreachable for `it support`, or for any
#: label not in `role_mapping.yaml` (which is every office role: "software
#: developer" text-searches, it has no venue type). Roles that DO have types
#: already get 20 per type from Nearby, so they stay on one page and pay for one
#: call. Capped because each page is a billed request and the shortlist is
#: `MAX_COMPANIES` long anyway.
MAX_TEXT_PAGES = 3


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


def _country_code(place: dict) -> str | None:
    """ISO-3166 alpha-2 for a Places result, lowercased ("au", "gb", "us").

    Read off the `country` address component, which the Pro field mask already
    pays for. This is what makes the search country-aware instead of AU-only:
    the per-company agent picks its job board from it (see
    `fmaj_agent.tools.impl.search_jobs_adzuna`).

    Returns None when Google gives no country component — a plus-code-only or
    unaddressed place. Callers must treat that as "unknown", never as a default
    country: guessing would send a Sydney cafe's search to a UK job index.
    """
    for comp in place.get("addressComponents") or []:
        if "country" in (comp.get("types") or []):
            short = (comp.get("shortText") or "").strip()
            if len(short) == 2 and short.isalpha():
                return short.lower()
    return None


def _to_candidate(place: dict, roles: list[str], source: str = "") -> dict:
    return {
        "source": source,
        "place_id": place["id"],
        "name": (place.get("displayName") or {}).get("text", ""),
        "address": place.get("formattedAddress", ""),
        "types": place.get("types", []),
        "lat": (place.get("location") or {}).get("latitude"),
        "lng": (place.get("location") or {}).get("longitude"),
        "country_code": _country_code(place),
        "roles": list(roles),
    }


def _majority_country(candidates: list[dict]) -> str | None:
    """The country most of the shortlist sits in, or None if none reported one."""
    counts: dict[str, int] = {}
    for cand in candidates:
        code = cand.get("country_code")
        if code:
            counts[code] = counts.get(code, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda c: counts[c])


def _as_specs(roles: list) -> list[RoleSpec]:
    """Accept plain strings (legacy) or RoleSpec/dicts."""
    specs = []
    for r in roles:
        if isinstance(r, RoleSpec):
            specs.append(r)
        elif isinstance(r, dict):
            specs.append(RoleSpec(**r))
        else:
            specs.append(RoleSpec(label=str(r)))
    return specs


def discover(
    lat: float,
    lng: float,
    radius_km: float,
    roles: list,
    client: PlacesClient | None = None,
    max_companies: int | None = None,
    fetch_details: bool = True,
) -> DiscoveryResult:
    # None -> use the configured budget; 0 there means "unlimited", which still
    # means HARD_MAX_COMPANIES because Place Details costs real money per call.
    if max_companies is None:
        max_companies = config.MAX_COMPANIES or HARD_MAX_COMPANIES
    max_companies = min(max_companies, HARD_MAX_COMPANIES)
    client = client or PlacesClient()
    radius_m = radius_km * 1000
    candidates: dict[str, dict] = {}
    specs = _as_specs(roles)
    labels = [s.label for s in specs]

    for spec in specs:
        # venue types come from the curated key; the label is what the agent hunts for
        plan = mapping.resolve(spec.mapping_key)
        if not plan.curated and spec.label != spec.mapping_key:
            plan = mapping.resolve(spec.label)
        raw: list[tuple[dict, str]] = []
        # ONE CALL PER TYPE, not one call with every type in it.
        #
        # Nearby Search (New) returns at most 20 places and has no pagination, so
        # a single bundled call is a hard ceiling of 20 candidates no matter how
        # big the radius or how many types are asked for. In Melbourne CBD at 5km
        # that produced 20 — which then had to cover a MAX_COMPANIES of 40.
        #
        # Splitting also improves the *mix*: `rankPreference: DISTANCE` on a
        # bundled call can return 20 restaurants and no bakeries, whereas per
        # type it returns the 20 nearest of each.
        #
        # Affordable because these are the Pro SKU (5K/month free) and the type
        # lists are short. Place Details — the Enterprise SKU, 1K/month — is
        # still only called for the shortlist, so this doesn't touch the
        # expensive half of discovery.
        for place_type in plan.types:
            raw.extend(
                (p, f"nearby:{place_type}")
                for p in client.search_nearby(lat, lng, radius_m, [place_type])
            )
        # Only pay for extra pages when Text Search is the ONLY source for this
        # role; with types in hand, Nearby has already supplied breadth. Several
        # queries share the page budget between them — three phrasings of one
        # page each beat one phrasing three pages deep, because the deeper pages
        # are the same query's long tail while a different phrasing finds
        # companies the first one never described.
        pages = 1
        if plan.text_queries and not plan.types:
            per_query = places_mod.PAGE_SIZE * len(plan.text_queries)
            pages = max(1, min(MAX_TEXT_PAGES, -(-max_companies // per_query)))
        for query in plan.text_queries:
            raw.extend(
                (p, f"text:{query}")
                for p in client.search_text(query, lat, lng, radius_m, max_pages=pages)
            )
        for place, source in raw:
            cand = _to_candidate(place, labels, source)
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

    # One country for the search, from the places nearest the pin. Individual
    # results can be missing a country component, and a search near a land border
    # can legitimately straddle two — the majority of the shortlist is a better
    # answer for those stragglers than dropping their job-board lookup entirely.
    search_country = _majority_country(shortlist)

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
                lat=cand["lat"],
                lng=cand["lng"],
                country_code=cand.get("country_code") or search_country,
                discovery_source=cand.get("source", ""),
            )
        )

    stats = {
        **client.stats.as_dict(),
        "raw_candidates": len(candidates),
        "within_radius": len(ranked),
        "shortlisted": len(companies),
        "with_website": sum(1 for c in companies if c.website),
        # Which call earned each place in the SHORTLIST — not the raw pool.
        # Distance ranking means a dense Nearby type can crowd the text queries
        # out of the cut entirely, so "we ran three queries" is not evidence any
        # of their results survived. Melbourne CBD x software developer: 39 of
        # 40 came from two Nearby types and exactly one from three text queries.
        "by_source": dict(
            sorted(
                Counter(c.discovery_source or "unknown" for c in companies).items(),
                key=lambda kv: -kv[1],
            )
        ),
        # Logged so a disappointing overseas search is diagnosable: "no listings"
        # reads very differently once you can see we resolved the wrong country,
        # or none at all.
        "country": search_country or "unknown",
    }
    logger.info("discovery stats: %s", stats)
    return DiscoveryResult(companies=companies, stats=stats)
