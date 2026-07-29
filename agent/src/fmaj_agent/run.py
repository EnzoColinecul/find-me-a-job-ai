"""Local runner for fast iteration: uv run python -m fmaj_agent.run --name "Cafe X" ..."""
import argparse

from fmaj_agent.models import Company
from fmaj_agent.orchestrator import investigate


def main() -> None:
    p = argparse.ArgumentParser(description="Investigate a single company")
    p.add_argument("--name", required=True)
    p.add_argument("--address", default="")
    p.add_argument("--website", default=None)
    p.add_argument("--role", action="append", required=True, dest="roles")
    args = p.parse_args()

    company = Company(
        place_id="local-test",
        name=args.name,
        address=args.address,
        website=args.website,
        roles=args.roles,
    )
    findings = investigate(company)
    print(findings.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
