#!/usr/bin/env python
"""Check the Seek employer-page title selector against the real site.

The role-match gate is only as good as the titles it is given, and those come
from one CSS selector (`[data-automation="jobTitle"]`) on a page we cannot reach
from the Cowork sandbox — its egress proxy blocks `au.seek.com`. So this has to
be run from a normal shell, and it is the thing to run first if AU listings ever
go quiet:

    cd agent && uv run python scripts/check_seek_titles.py "Virtual IT Group"

A non-zero `job_count` with an empty title list means Seek's markup moved. The
agent fails closed in that case — it stops linking to Seek rather than linking to
something it can't vouch for — so the symptom is "no Seek results any more",
not a wrong result.

Conduct: this fetches exactly the page `find_seek_company_page` already fetches,
reads titles only, and prints them. Same rules as the tool — see CLAUDE.md.
"""
import sys

sys.path.insert(0, "src")

from fmaj_agent.tools import impl  # noqa: E402


def main(names: list[str]) -> int:
    bad = 0
    for name in names:
        slug = impl._seek_company_slug(name)
        url = impl.SEEK_COMPANY_URL.format(slug=slug)
        result = impl.find_seek_company_page(name, country_code="au")
        print(f"\n{name}\n  {url}")
        if not result.ok:
            print(f"  no listing: {result.reason}")
            continue
        titles = result.data.get("job_titles") or []
        print(f"  job_count={result.data['job_count']}  titles={len(titles)}")
        for title in titles:
            print(f"    - {title}")
        if result.data["job_count"] and not titles:
            print("  !! markers found but no titles — the selector has drifted")
            bad = 1
    return bad


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["Virtual IT Group", "Elegant Media"]))
