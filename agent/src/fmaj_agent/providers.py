"""Provider-agnostic LLM layer for the agent.

The orchestrator speaks a normalized message format; each provider converts to/from
its native API. Swap with FMAJ_LLM_PROVIDER=bedrock|gemini.

Normalized messages (list[dict]):
  {"role": "user",      "text": "..."}
  {"role": "assistant", "text": "...", "tool_uses": [ToolUse, ...]}
  {"role": "tool",      "results": [{"id","name","output": dict}, ...]}

Provider-neutral tool defs — one JSON schema per tool, adapted per provider.
"""
from dataclasses import dataclass, field

from fmaj_agent import config


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
    {"name": "web_search",
     "description": ("Google search (SerpAPI). Use site:seek.com.au or "
                     "site:linkedin.com/jobs with the company name. Returns links only."),
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
                 max_tokens: int = 1024) -> Turn:
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
                 force_tool=None, max_tokens=1024) -> Turn:
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
        resp = self._client.converse(**kwargs)
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
        from google import genai
        self._genai = genai
        self._client = genai.Client(
            vertexai=True, project=config.VERTEX_PROJECT, location=config.VERTEX_LOCATION
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
                 force_tool=None, max_tokens=1024) -> Turn:
        from google.genai import types
        cfg: dict = {"temperature": 0, "max_output_tokens": max_tokens}
        if system:
            cfg["system_instruction"] = system
        if use_tools:
            cfg["tools"] = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters=t["parameters"]) for t in TOOLS])]
            mode = "ANY" if force_tool else "AUTO"
            fcc = types.FunctionCallingConfig(mode=mode)
            if force_tool:
                fcc.allowed_function_names = [force_tool]
            cfg["tool_config"] = types.ToolConfig(function_calling_config=fcc)
        resp = self._client.models.generate_content(
            model=model, contents=self._to_contents(messages),
            config=types.GenerateContentConfig(**cfg))

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
