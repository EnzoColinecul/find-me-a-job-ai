"""Eval runner: score the agent against evals/golden.yaml.

Metrics:
  - type accuracy: findings.opportunity_type in case's accepted set
  - link liveness: reported links respond < 400 (HEAD, fallback GET)
  - honesty: fabricated-company case must return none
Targets (Notion "Agent eval set" card): >= 75% type accuracy, >= 90% links alive.

Costs per full run (~14 cases): Vertex tokens (cheap) + up to ~2-3 SerpAPI searches
per case — watch the SerpAPI free tier (~100-250/mo). Use --limit N while iterating.

Usage (from agent/):
  AWS_PROFILE=fmaj-deploy GOOGLE_APPLICATION_CREDENTIALS=../project-*.json \
  FMAJ_LLM_PROVIDER=gemini uv run python evals/run_evals.py [--limit 3] [--case NAME]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fmaj_agent.models import Company  # noqa: E402
from fmaj_agent.orchestrator import investigate  # noqa: E402

GOLDEN = Path(__file__).parent / "golden.yaml"


def link_alive(url: str) -> bool:
    try:
        r = httpx.head(url, timeout=8, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0 (eval check)"})
        if r.status_code in (403, 405):  # some sites block HEAD
            r = httpx.get(url, timeout=8, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (eval check)"})
        return r.status_code < 400
    except Exception:
        return False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    p.add_argument("--case", default=None, help="run a single case by (partial) name")
    p.add_argument("--no-liveness", action="store_true", help="skip link HTTP checks")
    args = p.parse_args()

    cases = yaml.safe_load(GOLDEN.read_text())["cases"]
    if args.case:
        cases = [c for c in cases if args.case.lower() in c["name"].lower()]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("No cases matched.")
        return

    rows, correct, links_total, links_alive = [], 0, 0, 0
    tokens_in = tokens_out = 0
    t0 = time.monotonic()

    for i, case in enumerate(cases, 1):
        company = Company(
            place_id=f"eval-{i}",
            name=case["name"],
            address=case.get("address", "Sydney NSW, Australia"),
            website=case.get("website"),
            types=case.get("types", []),
            roles=case["roles"],
        )
        run = investigate(company)
        got = run.findings.opportunity_type.value
        ok = got in case["accept"]
        correct += ok
        tokens_in += run.input_tokens
        tokens_out += run.output_tokens

        alive_str = "-"
        if run.findings.links and not args.no_liveness:
            alive = [link_alive(u) for u in run.findings.links]
            links_total += len(alive)
            links_alive += sum(alive)
            alive_str = f"{sum(alive)}/{len(alive)}"

        rows.append({
            "case": case["name"], "expected": "|".join(case["accept"]), "got": got,
            "ok": ok, "links_alive": alive_str, "tool_calls": run.tool_calls,
            "seconds": round(run.seconds, 1),
            "evidence": run.findings.evidence[:100],
        })
        mark = "✅" if ok else "❌"
        print(f"{mark} [{i}/{len(cases)}] {case['name']}: got={got} "
              f"expected={case['accept']} tools={run.tool_calls} {run.seconds:.0f}s")

    accuracy = correct / len(cases)
    liveness = (links_alive / links_total) if links_total else None
    summary = {
        "cases": len(cases),
        "type_accuracy": round(accuracy, 2),
        "links_alive": f"{links_alive}/{links_total}" if links_total else "n/a",
        "link_liveness": round(liveness, 2) if liveness is not None else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_seconds": round(time.monotonic() - t0, 1),
        "pass": accuracy >= 0.75 and (liveness is None or liveness >= 0.9),
    }

    out = Path(__file__).parent / f"results-{int(time.time())}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nDetailed results -> {out}")
    if not summary["pass"]:
        print("\n⚠️ Below target (>=75% accuracy, >=90% links alive). Inspect the "
              "failing rows — stale golden labels are as likely as agent bugs.")


if __name__ == "__main__":
    main()
