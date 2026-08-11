"""Provider-agnostic LLM layer for the agent.  # noqa: D400

The orchestrator speaks a normalized message format; each provider converts to/from
its native API. Swap with FMAJ_LLM_PROVIDER=bedrock|gemini.

Normalized messages (list[dict]):
  {"role": "user",      "text": "..."}
  {"role": "assistant", "text": "...", "tool_uses": [ToolUse, ...]}
  {"role": "tool",      "results": [{"id","name","output": dict}, ...]}

Provider-neutral tool defs — one JSON schema per tool, adapted per provider.
"""
import logging
import time
from dataclasses import dataclass, field

from fmaj_agent import config

logger = logging.getLogger(__name__)

# Transient failures worth retrying (DNS blips, read timeouts, 429/503 from the API).
_RETRY_HINTS = (
    "connecterror", "readtimeout", "timeout", "nodename", "temporarily",
    "429", "503", "unavailable", "deadline",
)
_MAX_ATTEMPTS = 3


def _with_retry(fn, what: str):
    """Call fn(), retrying transient network/model errors with backoff."""
    last: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}".lower()
            if not any(h in msg for h in _RETRY_HINTS) or attempt == _MAX_ATTEMPTS:
                raise
            last = exc
            delay = 2 ** attempt  # 2s, 4s
            logger.warning("%s transient failure (attempt %d/%d), retrying in %ds: %s",
                           what, attempt, _MAX_ATTEMPTS, delay, exc)
            time.sleep(delay)
    raise last  # pragma: no cover


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict
    # Gemini 3 returns a thought_signature on function-call parts that MUST be echoed
    # back on the next turn (bytes). Unused by Bedrock.
    signature: bytes | None = None


@dataclass
class Turn:
    text: str = ""
    tool_uses: list[ToolUse] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


TOOLS = [
    {"name": "fetch_url",
     "description": "Fetch a web page and return its main text (truncated).",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                    "required": ["url"]}},
    {"name": "find_careers_link",
     "description": "Scan a company homepage for careers/jobs page links.",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                    "required": ["url"]}},
    {"name": "search_jobs_adzuna",
     "description": "Search Adzuna (AU job board) for live postings at a company.",
     "parameters": {"type": "object", "properties": {
         "company": {"type": "string"}, "role": {"type": "string"}},
         "required": ["company", "role"]}},
    {"name": "find_seek_company_page",
     "description": ("Check whether Seek has an employer-scoped listings page "
                     "(au.seek.com/<company>-jobs/at-this-company) for this company. "
                     "Prefer this over a blind site:seek.com web_search — it filters to "
                     "this employer instead of matching the name as a search term. "
                     "Returns the URL only if it resolves; no page content is read."),
     "parameters": {"type": "object", "properties": {"company": {"type": "string"}},
                    "required": ["company"]}},
    {"name": "web_search",
     "description": ("Google search (SerpAPI). For Seek, try find_seek_company_page "
                     "first; use this for site:linkedin.com/jobs, or only as a weak "
                     "last-resort site:seek.com name search. Returns links only."),
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"]}},
    {"name": "extract_emails",
     "description": "Scrape a contact/about page for recruitment emails.",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                    "required": ["url"]}},
    {"name": "report_findings",
     "description": "Report the final result. Call exactly once when done.",
     "parameters": {"type": "object", "properties": {
         "opportunity_type": {"type": "string",
             "enum": ["careers_page", "job_listing", "contact_email", "none"]},
         "links": {"type": "array", "items": {"type": "string"}},
         "emails": {"type": "array", "items": {"type": "string"}},
         "evidence": {"type": "string"},
         "confidence": {"type": "number"}},
         "required": ["opportunity_type", "evidence", "confidence"]}},
]


class Provider:
    def complete(self, system: str, messages: list[dict], *, model: str,
                 use_tools: bool = True, force_tool: str | None = None,
                 max_tokens: int = 1024, json_mode: bool = False) -> Turn:
        """json_mode: ask the provider to guarantee a JSON response where supported."""
        raise NotImplementedError


# ── Bedrock (Anthropic Claude) ────────────────────────────
class BedrockProvider(Provider):
    def __init__(self) -> None:
        import boto3
        self._client = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)

    @staticmethod
    def _to_messages(messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": [{"text": m["text"]}]})
            elif m["role"] == "assistant":
                content = []
                if m.get("text"):
                    content.append({"text": m["text"]})
                for tu in m.get("tool_uses", []):
                    content.append({"toolUse": {"toolUseId": tu.id, "name": tu.name,
                                                "input": tu.input}})
                out.append({"role": "assistant", "content": content or [{"text": ""}]})
            elif m["role"] == "tool":
                content = [{"toolResult": {"toolUseId": r["id"],
                                           "content": [{"json": r["output"]}]}}
                           for r in m["results"]]
                out.append({"role": "user", "content": content})
        return out

    def complete(self, system, messages, *, model, use_tools=True,
                 force_tool=None, max_tokens=1024, json_mode=False) -> Turn:
        # Claude has no JSON mode flag; the prompt already demands JSON.
        kwargs = {
            "modelId": model,
            "messages": self._to_messages(messages),
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        if use_tools:
            tool_config = {"tools": [{"toolSpec": {
                "name": t["name"], "description": t["description"],
                "inputSchema": {"json": t["parameters"]}}} for t in TOOLS]}
            if force_tool:
                tool_config["toolChoice"] = {"tool": {"name": force_tool}}
            kwargs["toolConfig"] = tool_config
        resp = _with_retry(lambda: self._client.converse(**kwargs), "bedrock.converse")
        usage = resp.get("usage", {})
        turn = Turn(input_tokens=usage.get("inputTokens", 0),
                    output_tokens=usage.get("outputTokens", 0))
        for c in resp["output"]["message"]["content"]:
            if "text" in c:
                turn.text += c["text"]
            elif "toolUse" in c:
                tu = c["toolUse"]
                turn.tool_uses.append(ToolUse(tu["toolUseId"], tu["name"],
                                              tu.get("input", {})))
        return turn


# ── Gemini (Google, via Vertex AI) ────────────────────────
class GeminiProvider(Provider):
    def __init__(self) -> None:
        import os

        from google import genai

        # In Lambda there's no key file on disk: fetch the SA key JSON from Secrets
        # Manager (FMAJ_GCP_SA_SECRET) and materialize it under /tmp once.
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            secret_name = os.environ.get("FMAJ_GCP_SA_SECRET")
            if secret_name:
                import boto3
                key_json = boto3.client(
                    "secretsmanager", region_name=config.AWS_REGION
                ).get_secret_value(SecretId=secret_name)["SecretString"]
                path = "/tmp/gcp-sa.json"  # noqa: S108 — Lambda's only writable dir
                with open(path, "w") as f:
                    f.write(key_json)
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path

        from google.genai import types as genai_types

        self._genai = genai
        self._client = genai.Client(
            vertexai=True,
            project=config.VERTEX_PROJECT,
            location=config.VERTEX_LOCATION,
            http_options=genai_types.HttpOptions(timeout=60_000),  # ms — never hang
        )

    def _to_contents(self, messages: list[dict]) -> list:
        from google.genai import types
        contents = []
        for m in messages:
            if m["role"] == "user":
                contents.append(types.Content(role="user",
                    parts=[types.Part.from_text(text=m["text"])]))
            elif m["role"] == "assistant":
                parts = []
                if m.get("text"):
                    parts.append(types.Part.from_text(text=m["text"]))
                for tu in m.get("tool_uses", []):
                    fp = types.Part.from_function_call(name=tu.name, args=tu.input)
                    if tu.signature is not None:
                        fp.thought_signature = tu.signature  # required by Gemini 3
                    parts.append(fp)
                contents.append(types.Content(role="model", parts=parts))
            elif m["role"] == "tool":
                parts = [types.Part.from_function_response(
                    name=r["name"], response=r["output"]) for r in m["results"]]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    def complete(self, system, messages, *, model, use_tools=True,
                 force_tool=None, max_tokens=1024, json_mode=False) -> Turn:
        from google.genai import types
        cfg: dict = {"temperature": 0, "max_output_tokens": max_tokens}
        if system:
            cfg["system_instruction"] = system
        if json_mode and not use_tools:
            # Guarantees parseable output. Gemini 3 spends part of the token budget on
            # thinking, so callers should also allow generous max_tokens.
            cfg["response_mime_type"] = "application/json"
        if use_tools:
            cfg["tools"] = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters=t["parameters"]) for t in TOOLS])]
            mode = "ANY" if force_tool else "AUTO"
            fcc = types.FunctionCallingConfig(mode=mode)
            if force_tool:
                fcc.allowed_function_names = [force_tool]
            cfg["tool_config"] = types.ToolConfig(function_calling_config=fcc)
        resp = _with_retry(
            lambda: self._client.models.generate_content(
                model=model, contents=self._to_contents(messages),
                config=types.GenerateContentConfig(**cfg)),
            "gemini.generate_content")

        turn = Turn()
        um = getattr(resp, "usage_metadata", None)
        if um:
            turn.input_tokens = getattr(um, "prompt_token_count", 0) or 0
            turn.output_tokens = getattr(um, "candidates_token_count", 0) or 0
        cand = (resp.candidates or [None])[0]
        if cand and cand.content and cand.content.parts:
            for i, part in enumerate(cand.content.parts):
                if getattr(part, "text", None):
                    turn.text += part.text
                fc = getattr(part, "function_call", None)
                if fc:
                    turn.tool_uses.append(ToolUse(
                        id=f"{fc.name}-{i}", name=fc.name, input=dict(fc.args or {}),
                        signature=getattr(part, "thought_signature", None)))
        return turn


_PROVIDERS = {"bedrock": BedrockProvider, "gemini": GeminiProvider}
_instance: Provider | None = None


def get_provider() -> Provider:
    global _instance
    if _instance is None:
        cls = _PROVIDERS.get(config.LLM_PROVIDER)
        if cls is None:
            raise ValueError(f"Unknown FMAJ_LLM_PROVIDER: {config.LLM_PROVIDER}")
        _instance = cls()
    return _instance
