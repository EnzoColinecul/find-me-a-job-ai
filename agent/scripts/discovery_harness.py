"""Discovery quality harness (Notion: "Discovery quality test harness").

Runs discovery for suburb x role combos against the REAL Places API and writes a CSV
for manual grading. Watch the printed call counts against the free tiers
(5K Pro search calls/mo, 1K Enterprise details calls/mo).

Usage (from agent/):
  export FMAJ_PLACES_KEY=...            # or rely on Secrets Manager via AWS creds
  uv run python scripts/discovery_harness.py                       # default combos
  uv run python scripts/discovery_harness.py --suburb "Newtown:-33.8983:151.1785" \
      --role barista --radius 2 --no-details
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fmaj_agent.discovery import discover  # noqa: E402
from fmaj_agent.places import PlacesClient  # noqa: E402

DEFAULT_SUBURBS = {
    "Surry Hills": (-33.8845, 151.2119),
    "Bondi Beach": (-33.8908, 151.2743),
    "Parramatta": (-33.8151, 151.0011),
    "Newtown": (-33.8983, 151.1785),
    "Manly": (-33.7969, 151.2855),
}
DEFAULT_ROLES = ["chef", "retail assistant", "electrician"]


def main() -> None:
    p = argparse.ArgumentParser(description="Run discovery quality checks")
    p.add_argument("--suburb", action="append", metavar="NAME:LAT:LNG",
                   help="override suburbs (repeatable)")
    p.add_argument("--role", action="append", help="override roles (repeatable)")
    p.add_argument("--radius", type=float, default=5.0)
    p.add_argument("--max", type=int, default=40)
    p.add_argument("--no-details", action="store_true",
                   help="skip Place Details (saves Enterprise quota; no websites)")
    p.add_argument("--out", default="discovery_results.csv")
    args = p.parse_args()

    suburbs = (
        {s.split(":")[0]: (float(s.split(":")[1]), float(s.split(":")[2]))
         for s in args.suburb}
        if args.suburb
        else DEFAULT_SUBURBS
    )
    roles = args.role or DEFAULT_ROLES

    client = PlacesClient()
    rows = []
    for suburb, (lat, lng) in suburbs.items():
        for role in roles:
            result = discover(
                lat, lng, args.radius, [role],
                client=client, max_companies=args.max,
                fetch_details=not args.no_details,
            )
            print(f"{suburb} x {role}: {result.stats}")
            for c in result.companies:
                rows.append({
                    "suburb": suburb,
                    "role": role,
                    "company": c.name,
                    "address": c.address,
                    "types": "|".join(c.types),
                    "website": c.website or "",
                    "relevant?": "",  # manual grading column
                })

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                                ["suburb", "role", "company"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{len(rows)} rows -> {args.out}")
    print(f"TOTAL Places calls this run: {client.stats.as_dict()}")


if __name__ == "__main__":
    main()
