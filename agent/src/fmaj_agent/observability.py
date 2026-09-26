"""Langfuse Cloud observability for searches — one trace per search.

What goes where
---------------
A search runs in several processes: the API starts it, a Discover Lambda finds
the companies, one Investigate Lambda per company runs the agent, and an
Aggregate Lambda closes it. They share no memory, so they share a trace id
instead: `trace_id_for(search_id)` is derived from the search id, and every
process opens its top-level observation inside that trace.

    search <search_id>                          trace
    ├── api.create_search                      span   (API Lambda)
    ├── discovery                              span   (Discover Lambda)
    ├── company                                agent  (one per Investigate Lambda)
    │   ├── triage                             generation
    │   ├── agent.turn                         generation (one per model turn)
    │   ├── tool.<name>                        tool   (one per tool call)
    │   │   └── role_match                     generation (when a gate judges titles)
    │   ├── budget.denied / report.downgraded  event
    │   └── forced_report                      generation (budget breach)
    └── aggregate | search.failed              span

Generations are recorded in ONE place — `providers.Provider.complete` — so the
Gemini and Bedrock paths are observed identically and a provider switch can
never go dark.

Rules this module keeps
-----------------------
* **Observability must never fail a search.** Every public function swallows
  its own errors. No keys, a bad key, Langfuse down, the `langfuse` package
  missing: all mean "tracing off", never an exception in the caller.
* **Nothing sensitive leaves.** We send ids, counts, names of things, token
  usage and timings — never prompts, completions, page bodies, company names or
  addresses (Places data may not be persisted beyond the search; `place_id` is
  exempt), applicant details, or credentials. `redact` is a second line of
  defence, installed as the client's `mask`, for anything that slips through.
* **Secrets stay server-side.** Keys come from the environment (local `.env`)
  or AWS Secrets Manager (`fmaj/{stage}/langfuse`), never from code.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fmaj_agent import config

logger = logging.getLogger(__name__)

#: Langfuse Cloud (EU). US/other regions: set LANGFUSE_BASE_URL.
DEFAULT_BASE_URL = "https://cloud.langfuse.com"

#: How long a Lambda may spend handing spans to Langfuse before it returns.
#: The export keeps going in the background; it is just no longer waited for.
FLUSH_TIMEOUT_SECONDS = 3.0

#: Seconds before an export request to Langfuse gives up.
EXPORT_TIMEOUT_SECONDS = 5

_OFF = object()
_client: Any = None  # None = not resolved yet; _OFF = disabled; else a Langfuse client
_lock = threading.Lock()


# ── configuration ─────────────────────────────────────────────────────────


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def _repo_env_file() -> Path:
    # agent/src/fmaj_agent/observability.py -> repo root
    return Path(__file__).resolve().parents[3] / ".env"


def _local_env_values() -> dict[str, str]:
    """LANGFUSE_* from the repo-root `.env`, for local development only.

    Deliberately NOT a general `load_dotenv`: that file also carries AWS access
    keys, which would silently override the `fmaj-deploy` profile if exported.
    Only the three Langfuse names are picked out, and only if not already set.
    Never runs in Lambda, where the file does not exist anyway.
    """
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return {}
    path = _repo_env_file()
    out: dict[str, str] = {}
    try:
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line.startswith("LANGFUSE_") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}
    return out


def _credentials() -> tuple[str, str, str] | None:
    """(public_key, secret_key, base_url), or None when tracing should be off.

    Resolution mirrors `fmaj_agent.secrets`: environment first (local dev),
    then the repo-root `.env`, then Secrets Manager (deployed stages, named by
    FMAJ_LANGFUSE_SECRET). FMAJ_LANGFUSE_ENABLED=0 turns it all off.
    """
    if not _truthy(os.environ.get("FMAJ_LANGFUSE_ENABLED")):
        return None
    local = _local_env_values()

    def get(name: str) -> str:
        return os.environ.get(name) or local.get(name) or ""

    public, secret = get("LANGFUSE_PUBLIC_KEY"), get("LANGFUSE_SECRET_KEY")
    base = get("LANGFUSE_BASE_URL") or get("LANGFUSE_HOST")
    if public and secret:
        return public, secret, base or DEFAULT_BASE_URL

    secret_name = os.environ.get("FMAJ_LANGFUSE_SECRET")
    if not secret_name:
        return None
    from fmaj_agent.secrets import _secret_string  # boto3 only when needed

    data = json.loads(_secret_string(secret_name))
    public, secret = data.get("public_key", ""), data.get("secret_key", "")
    if not (public and secret):
        return None
    return public, secret, data.get("base_url") or base or DEFAULT_BASE_URL


def _environment() -> str:
    """Langfuse environment: LANGFUSE_TRACING_ENVIRONMENT, else the stage.

    Langfuse only accepts [a-z0-9_-] and rejects a leading "langfuse".
    """
    raw = os.environ.get("LANGFUSE_TRACING_ENVIRONMENT") or config.STAGE or "default"
    env = re.sub(r"[^a-z0-9_-]", "-", raw.lower())[:40] or "default"
    return "env-" + env if env.startswith("langfuse") else env


def _build_client() -> Any:
    creds = _credentials()
    if creds is None:
        logger.info("langfuse tracing disabled (no configuration)")
        return _OFF
    from langfuse import Langfuse

    public, secret, base = creds
    return Langfuse(
        public_key=public,
        secret_key=secret,
        base_url=base,
        environment=_environment(),
        release=os.environ.get("FMAJ_RELEASE") or None,
        timeout=EXPORT_TIMEOUT_SECONDS,
        mask=_mask,
    )


def client() -> Any | None:
    """The Langfuse client, or None when tracing is off. Never raises."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                try:
                    _client = _build_client()
                except Exception:
                    logger.warning("langfuse tracing disabled (setup failed)", exc_info=True)
                    _client = _OFF
    return None if _client is _OFF else _client


def enabled() -> bool:
    return client() is not None


def set_client(value: Any | None) -> None:
    """Install a client (tests), or None to force re-resolution from config."""
    global _client
    _client = value


def disable() -> None:
    global _client
    _client = _OFF


def trace_id_for(search_id: str) -> str:
    """Deterministic 32-hex Langfuse trace id for a search.

    Identical to `Langfuse.create_trace_id(seed=f"fmaj-search:{search_id}")`
    (sha256 of the seed, first 16 bytes as hex); computed here so the API can
    record it even with tracing off.
    """
    return hashlib.sha256(f"fmaj-search:{search_id}".encode()).hexdigest()[:32]


def trace_url(search_id: str) -> str | None:
    lf = client()
    if lf is None:
        return None
    try:
        return lf.get_trace_url(trace_id=trace_id_for(search_id))
    except Exception:  # noqa: BLE001
        return None


def flush(timeout: float = FLUSH_TIMEOUT_SECONDS) -> None:
    """Hand pending spans to Langfuse, waiting at most `timeout` seconds.

    Lambdas freeze once the handler returns, so this runs at the end of each
    handler. It is bounded because an unreachable Langfuse must not add its own
    retry budget onto a search.
    """
    lf = client()
    if lf is None:
        return

    def _run() -> None:
        try:
            lf.flush()
        except Exception:
            logger.warning("langfuse flush failed", exc_info=True)

    worker = threading.Thread(target=_run, name="langfuse-flush", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        logger.warning("langfuse flush still running after %.1fs; not waiting", timeout)


# ── redaction ─────────────────────────────────────────────────────────────

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BEARER = re.compile(r"\bbearer\s+[\w.~+/=-]+", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+")
_SECRETISH = re.compile(
    r"\b(?:sk-lf-|pk-lf-|sk-|AIza|ya29\.|AKIA|ASIA)[\w-]{8,}"  # Langfuse, Google, AWS…
    r"|\b[A-Fa-f0-9]{40,}\b"  # long hex tokens (SerpAPI keys are 64-hex)
)
#: Keys whose values are never sent, whatever they hold: credentials, and the
#: fields that would carry prompt/completion/page text.
_DENY_KEYS = re.compile(
    r"secret|password|passwd|(^|_)token$|authorization|cookie|credential|"
    r"^key$|(^|_)(api|app|secret|private|access)_?key$|"
    r"^(text|html|body|content|pages?|prompt|messages?|snippets?|system|"
    r"emails?|address|company|name|query_text)$",
    re.IGNORECASE,
)
MAX_STRING = 240


def _url_host(match: re.Match) -> str:
    url = match.group(0)
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/", 1)[0].split("?", 1)[0]
    return f"<url:{host.split('@')[-1].lower()}>"


#: Strings that must not leave while they are set — the company being
#: investigated (name, address, website host). Tool refusals and gate reasons
#: echo their inputs, so a generic scrubber is not enough on its own.
_sensitive: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "fmaj_obs_sensitive", default=()
)


@contextlib.contextmanager
def sensitive(*terms: str | None) -> Iterator[None]:
    """Scrub these terms from everything recorded inside the block."""
    clean = tuple(sorted({t.strip() for t in terms if t and len(t.strip()) >= 3},
                         key=len, reverse=True))
    token = _sensitive.set(_sensitive.get() + clean)
    try:
        yield
    finally:
        _sensitive.reset(token)


def host_of(url: str | None) -> str | None:
    if not url:
        return None
    host = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE).split("/", 1)[0]
    host = host.split("?", 1)[0].split("@")[-1].lower()
    return host[4:] if host.startswith("www.") else host or None


def redact_text(value: str) -> str:
    """Scrub one string: credentials, emails, URLs (to their host), the
    company in scope, length."""
    out = _BEARER.sub("[redacted-token]", value)
    out = _JWT.sub("[redacted-token]", out)
    out = _SECRETISH.sub("[redacted-secret]", out)
    out = _EMAIL.sub("[email]", out)
    out = _URL.sub(_url_host, out)
    for term in _sensitive.get():
        out = re.sub(re.escape(term), "[company]", out, flags=re.IGNORECASE)
    if len(out) > MAX_STRING:
        out = out[:MAX_STRING] + "…"
    return out


def redact(data: Any, _depth: int = 0) -> Any:
    """Recursively scrub a JSON-ish value. Never raises."""
    try:
        if _depth > 6:
            return "[truncated]"
        if isinstance(data, str):
            return redact_text(data)
        if isinstance(data, (bool, int, float)) or data is None:
            return data
        if isinstance(data, dict):
            return {
                str(k): "[redacted]" if _DENY_KEYS.search(str(k)) else redact(v, _depth + 1)
                for k, v in list(data.items())[:50]
            }
        if isinstance(data, (list, tuple, set)):
            return [redact(v, _depth + 1) for v in list(data)[:50]]
        return redact_text(str(data))
    except Exception:  # noqa: BLE001
        return "[redaction-failed]"


def _mask(*, data: Any, **_kwargs: Any) -> Any:
    """Langfuse `mask` hook: applied to every input, output and metadata."""
    return redact(data)


# ── observations ──────────────────────────────────────────────────────────


class _Noop:
    """Stands in for an observation when tracing is off. Accepts everything."""

    def update(self, **_kw: Any) -> None:
        pass

    def event(self, *_a: Any, **_kw: Any) -> None:
        pass

    def error(self, *_a: Any, **_kw: Any) -> None:
        pass


NOOP = _Noop()


class Observation:
    """Thin, never-raising wrapper over a Langfuse observation."""

    def __init__(self, lf: Any, span: Any) -> None:
        self._lf = lf
        self._span = span

    def update(self, **kwargs: Any) -> None:
        try:
            if "metadata" in kwargs:
                kwargs["metadata"] = _clean_meta(kwargs["metadata"])
            if kwargs.get("status_message"):
                # Not covered by Langfuse's mask, which sees input/output/metadata.
                kwargs["status_message"] = redact_text(str(kwargs["status_message"]))
            self._span.update(**kwargs)
        except Exception:
            logger.debug("langfuse update failed", exc_info=True)

    def event(self, name: str, *, level: str = "DEFAULT", metadata: dict | None = None,
              status_message: str | None = None) -> None:
        """A point-in-time marker nested under this observation."""
        try:
            self._span.create_event(
                name=name, level=level, metadata=_clean_meta(metadata),
                status_message=redact_text(status_message) if status_message else None,
            )
        except Exception:
            logger.debug("langfuse event failed", exc_info=True)

    def error(self, message: str) -> None:
        self.update(level="ERROR", status_message=message)


def _clean_meta(meta: dict | None) -> dict | None:
    if not meta:
        return None
    return {k: v for k, v in meta.items() if v is not None and v != ""}


def _trace_attrs(trace_meta: dict | None, tags: list[str] | None) -> dict:
    """Arguments for `propagate_attributes`: strings only, ≤200 chars each."""
    meta = {
        k: redact_text(str(v))[:200]
        for k, v in (trace_meta or {}).items()
        if v is not None and v != ""
    }
    meta.setdefault("stage", config.STAGE)
    return {
        "trace_name": "search",
        "metadata": meta,
        "tags": [t[:200] for t in (tags or []) if t],
    }


@contextlib.contextmanager
def observe(
    name: str,
    *,
    as_type: str = "span",
    search_id: str | None = None,
    new_trace: bool = False,
    trace_name: str | None = None,
    trace_meta: dict | None = None,
    tags: list[str] | None = None,
    **fields: Any,
) -> Iterator[Observation | _Noop]:
    """Open an observation. Yields a handle whose methods never raise.

    `search_id` pins the observation into that search's trace (use it for the
    TOP-LEVEL observation of each process only — nested ones inherit their
    parent). `new_trace` starts a fresh trace for work with no search (role
    interpretation, a local single-company run). Exceptions from the body are
    recorded as ERROR and re-raised unchanged; errors from Langfuse itself are
    swallowed.
    """
    lf = client()
    if lf is None:
        yield NOOP
        return

    stack = contextlib.ExitStack()
    handle: Observation | _Noop = NOOP
    try:
        top = bool(search_id) or new_trace
        if top:
            from langfuse import propagate_attributes

            attrs = _trace_attrs(trace_meta, tags)
            if trace_name:
                attrs["trace_name"] = trace_name
            stack.enter_context(propagate_attributes(**attrs))
        kwargs: dict[str, Any] = {"name": name, "as_type": as_type}
        if search_id:
            kwargs["trace_context"] = {"trace_id": trace_id_for(search_id)}
        if "metadata" in fields:
            fields["metadata"] = _clean_meta(fields["metadata"])
        if fields.get("status_message"):
            fields["status_message"] = redact_text(str(fields["status_message"]))
        kwargs.update(fields)
        span = stack.enter_context(lf.start_as_current_observation(**kwargs))
        handle = Observation(lf, span)
    except Exception:
        logger.warning("langfuse observation %r not started", name, exc_info=True)
        _close(stack)
        stack = contextlib.ExitStack()
        handle = NOOP

    try:
        yield handle
    except BaseException as exc:
        if isinstance(handle, Observation) and not isinstance(exc, GeneratorExit):
            handle.error(f"{type(exc).__name__}: {exc}")
        _close(stack)
        raise
    else:
        _close(stack)


def _close(stack: contextlib.ExitStack) -> None:
    try:
        stack.close()
    except Exception:
        logger.debug("langfuse observation close failed", exc_info=True)


def current_event(name: str, *, level: str = "DEFAULT", metadata: dict | None = None,
                  status_message: str | None = None) -> None:
    """Record an event under whatever observation is current. Never raises."""
    lf = client()
    if lf is None:
        return
    try:
        lf.create_event(
            name=name, level=level, metadata=_clean_meta(metadata),
            status_message=redact_text(status_message) if status_message else None,
        )
    except Exception:
        logger.debug("langfuse event failed", exc_info=True)


# ── cost ──────────────────────────────────────────────────────────────────


def _price_table() -> dict[str, tuple[float, float]]:
    """USD per 1M tokens (input, output) from FMAJ_LLM_PRICES, e.g.
    '{"gemini-3.6-flash": [0.3, 2.5]}'. Empty by default: Langfuse Cloud prices
    known models itself, and a custom model is better defined once in Langfuse
    (Settings → Models) than guessed here. This is the override.
    """
    raw = os.environ.get("FMAJ_LLM_PRICES")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): (float(v[0]), float(v[1])) for k, v in data.items()}
    except Exception:  # noqa: BLE001
        logger.warning("FMAJ_LLM_PRICES is not valid JSON {model: [in, out]}; ignored")
        return {}


def cost_details(model: str, input_tokens: int, output_tokens: int) -> dict[str, float] | None:
    price = _price_table().get(model)
    if price is None:
        return None
    cost_in = input_tokens * price[0] / 1_000_000
    cost_out = output_tokens * price[1] / 1_000_000
    return {"input": cost_in, "output": cost_out, "total": cost_in + cost_out}


def tool_output_summary(result: Any) -> dict:
    """What we record of a tool result: status and shape, never the content."""
    if result is None:
        return {"ok": False, "reason": "unknown tool"}
    data = getattr(result, "data", {}) or {}
    summary: dict[str, Any] = {"ok": bool(getattr(result, "ok", False))}
    reason = getattr(result, "reason", "")
    if reason:
        summary["reason"] = redact_text(str(reason))
    shape: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (list, tuple, dict, str)):
            shape[f"{key}_count" if not isinstance(value, str) else f"{key}_chars"] = len(value)
        elif isinstance(value, (bool, int, float)):
            shape[key] = value
    if shape:
        summary["data"] = shape
    return summary


def tool_input_summary(args: dict | None) -> dict:
    """Argument names and sizes only: URLs and queries carry company names and
    Places-sourced websites, which must not be persisted beyond the search."""
    return {str(k): f"<{type(v).__name__}:{len(str(v))}>" for k, v in (args or {}).items()}


def main(argv: list[str] | None = None) -> None:
    """`python -m fmaj_agent.observability <search_id>` → trace id (and URL)."""
    import sys

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m fmaj_agent.observability <search_id>")
        raise SystemExit(2)
    for search_id in args:
        url = trace_url(search_id)
        print(f"{search_id}\t{trace_id_for(search_id)}\t{url or '(tracing not configured)'}")


if __name__ == "__main__":
    main()
