# Design spec — Find Me A Job AI

Extracted from `Find Me A Job AI - Mockups.html` (Claude design project, 2026-08-04).
`mockups-extracted.html` is the decoded markup — open it to check exact values.
The bundle is base64+gzip; re-extract with the snippet at the bottom.

## Direction

Warm, paper-like editorial UI — cream backgrounds, a stylised street map, navy ink.
Deliberately *not* a generic SaaS dashboard. Tagline: **"Your next job, found street
by street."** The map is the hero on every screen; the agent's work is shown openly
("Live view of every step — nothing hidden").

## Tokens

| Token | Value | Use |
|---|---|---|
| `--bg-paper` | `#f6f5f2` / `#f2f0e9` | app background |
| `--surface` | `#fffdf7` | cards, panels |
| `--border` | `#ddd6c2` | hairlines, card borders |
| `--border-soft` | `#e6e0cf` | inner dividers |
| `--ink` | `#14213d` | primary text, logo navy |
| `--ink-muted` | `#8b8574` | secondary text on paper |
| `--slate-muted` | `#6b7280` / `#9aa1ab` | secondary text on white |
| `--accent` | `#3d6fb5` | primary actions, links |
| `--accent-strong` | `#2f6fed` | focus/active |
| `--pin` | `#ff5a45` | map pin, location marker |
| `--success` | `#2fa572` / `#4f8c62` | found/complete |
| `--warn` | `#ff8a3d` | in-progress |
| `--pink` | `#e64f8a` | accent chip |
| `--purple` | `#8a4bd6` | accent chip |
| Map fills | `#cfe8d1` park · `#a8d7ee` water · `#f7edd3` block · `#fffdf7` road | |

Type: **Inter** (400/500/600/700).
Radii: `2px` map/tags · `8px` cards · `12px` panels · `999px` pills.

## Screens

### 1 · Login
Full-bleed street map background, centered card: logo, product name, tagline,
**"Continue with Google"**, and "By continuing, you agree to our Terms and Privacy
Policy." Desktop and mobile.

### 2 · First visit — home
Greeting **"Hello Alex — what role do you want next?"** with subtext "Tell me a little
about your experience too, and I'll search the streets around you." One large input:
*"Ask me for a job — e.g. kitchen work near Surry Hills"*, plus quick-pick pills:
Line cook · Kitchen hand · Barista · Retail assistant.

### 3 · Workspace — three panes (desktop)
- **Left rail:** New search · Recent searches (`Line cook · Surry Hills`) · Your profile
  (avatar, name, email, "Kitchen experience · 2 yrs", "Full time · Surry Hills")
- **Centre:** map, "Drag the pin to move the centre", address label
- **Right:** "Ready when you are" → "I found 2 roles that match what you told me",
  **Roles detected** chips (Line Cook, Kitchen Hand), **Search radius** 1/5/10 km,
  **Start analysis**

### 4 · Results
Header `Line cook · Surry Hills NSW 2010 · 5 km` + **Refine**. Status line
"Search complete — 3 places worth contacting". Section **Jobs found** / "3 companies
nearby · updated just now". Cards: company, address, then source-labelled links
(`seek.com.au/companies/…`, `marloweskitchen.com.au/careers`,
`indeed.com/cmp/…`, `facebook.com/…/jobs`) and emails with a **Copy** button.

### 5 · Analysis running (animated)
Header with **Stop**. Progress "Looking at 4 of 9 places nearby". Panel **What I'm
doing** — "Live view of every step — nothing hidden" — streaming rows of
`tag · text · tool · meta`:

| tag | tool | meta |
|---|---|---|
| Searching | `places.nearby` | 9 places found |
| Checking | `fetch_page` | marloweskitchen.com.au |
| Found | `extract_jobs` | 2 matches |
| Checking | `web_search` | "Harborview Hotel jobs" |
| Found | `extract_contact` | 1 email |
| Skipping | `places.details` | no longer trading |

These map 1:1 onto our real tools (`places.nearby` → discovery, `fetch_page` →
`fetch_url`, `extract_jobs` → careers/Adzuna, `web_search` → SerpAPI,
`extract_contact` → `extract_emails`), so the backend can already emit them.

### Mobile
Login · Set up the search ("Hi, Alex") · Results (`Surry Hills · 1 km radius`,
"Job listings", "3 companies found nearby").

## Gaps vs. current build

- We have: Google login, map+radius, free-text roles, results grouped by type.
- **Missing:** the whole visual language; three-pane workspace; live agent trace;
  profile/recent searches; source-labelled links; Copy button; mobile layouts.
- **Backend needs:** per-step progress events for the live trace; a user profile
  (experience/availability); recent-search history.

## Re-extracting the bundle

```python
import re, base64, gzip
s = open("Find Me A Job AI - Mockups.html", encoding="utf-8", errors="replace").read()
t = re.search(r'<script type="__bundler/template">(.*?)</script>', s, re.S).group(1)
# blobs: re.findall(r'"([A-Za-z0-9+/=]{200,})"', s) → base64 → gzip.decompress
```
