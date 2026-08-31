"""Local runner: investigate ONE company end-to-end (real Bedrock + tools).

Requires AWS creds (Bedrock + Secrets Manager) and enabled model access. Example:
  AWS_PROFILE=fmaj-deploy uv run python -m fmaj_agent.run \\
      --name "Single O Surry Hills" --website https://singleo.com.au/ \\
      --role barista --country au
"""
import argparse
import json
import logging

from fmaj_agent.models import Company
from fmaj_agent.orchestrator import investigate


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Investigate a single company")
    p.add_argument("--name", required=True)
    p.add_argument("--website", default=None)
    p.add_argument("--address", default="")
    p.add_argument("--types", default="", help="comma-separated Places types")
    p.add_argument("--role", action="append", required=True, dest="roles")
    p.add_argument(
        "--country",
        default=None,
        help="ISO-3166 alpha-2 (au, gb, us…). In a real search this comes from "
             "Places; here it decides which job boards the agent may use. Omit it "
             "and the country-specific boards are skipped.",
    )
    args = p.parse_args()

    company = Company(
        place_id="local-test",
        name=args.name,
        address=args.address,
        website=args.website,
        types=[t.strip() for t in args.types.split(",") if t.strip()],
        roles=args.roles,
        country_code=(args.country or "").lower() or None,
    )
    run = investigate(company)
    print("\n=== FINDINGS ===")
    print(json.dumps(run.findings.model_dump(), indent=2, default=str))
    print("\n=== STATS ===")
    print(json.dumps(run.stats(), indent=2))
    print("\n=== TRACE ===")
    for step in run.trace:
        print(" •", step)


if __name__ == "__main__":
    main()
