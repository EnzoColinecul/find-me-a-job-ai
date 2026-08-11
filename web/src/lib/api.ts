import { getToken } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL!;

export interface Me {
  sub: string;
  email: string;
  name: string | null;
  free_search_used: boolean;
}

/** Fetch the signed-in user's profile, or null if not authenticated. */
export async function getMe(): Promise<Me | null> {
  const token = getToken();
  if (!token) return null;
  const resp = await fetch(`${API_URL}/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (resp.status === 401) return null;
  if (!resp.ok) throw new Error(`/me failed: ${resp.status}`);
  return resp.json();
}

export interface RoleSpec {
  label: string;
  curated_key?: string | null;
}

export interface RoleSuggestion extends RoleSpec {
  why?: string;
}

export interface AppConfig {
  max_roles: number;
  max_radius_km: number;
  radius_options_km: number[];
}

export interface SearchParams {
  lat: number;
  lng: number;
  radius_km: number;
  roles: RoleSpec[];
  query_text?: string;
  /** Human-readable place the user picked, e.g. "Surry Hills NSW 2010". */
  location_label?: string;
}

/** A row in the workspace's recent-searches rail. Descriptive only — no status. */
export interface SearchSummary {
  search_id: string;
  roles: string[];
  location_label: string;
  lat: number;
  lng: number;
  radius_km: number;
  created_at: string;
}

export interface SearchResult {
  place_id: string;
  company: string;
  address: string;
  opportunity_type: string;
  links: string[];
  emails: string[];
  /** The agent's one-line justification for returning this company. */
  evidence: string;
  /** The company's own site — used to tell their careers page from a job board. */
  website: string;
  /**
   * Map coordinates for the numbered pin. Optional and nullable: they live on a
   * TTL'd item, so older or expired searches return null and the card simply
   * gets no marker on the map.
   */
  lat?: number | null;
  lng?: number | null;
}

/** One row of the live "What I'm doing" panel. */
export interface TraceStep {
  tag: "searching" | "checking" | "found" | "skipping";
  /** Friendly tool name, e.g. "fetch_page". Mapped server-side. */
  tool: string;
  text: string;
  meta: string;
  at: string;
}

export interface Search {
  search_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  /** How many discovered companies the agent has finished. */
  progress: { done: number; total: number };
  steps: TraceStep[];
  /** Roles come back as plain labels here, not RoleSpecs. */
  params: Omit<SearchParams, "roles"> & { roles: string[] };
  results: SearchResult[];
  total: number;
}

/**
 * A failure the API named. `code` is stable and safe to branch on; `message` is
 * the copy the API wants shown, so wording changes don't need a web deploy.
 */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Turn any non-OK response into an ApiError.
 *
 * Tolerates three shapes on purpose: the structured `{code, message}` envelope,
 * FastAPI's plain-string `detail` (422 validation errors still use it), and a
 * body that isn't JSON at all — a gateway timeout or a 502 from in front of the
 * app never reaches our exception handler, and "Unexpected token < in JSON" is
 * not something to show a job seeker.
 */
async function fail(resp: Response, fallback: string): Promise<never> {
  const body = await resp.json().catch(() => null);
  const detail = body?.detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    throw new ApiError(
      String(detail.code),
      String(detail.message ?? fallback),
      resp.status,
    );
  }
  throw new ApiError(
    "unknown",
    typeof detail === "string" ? detail : `${fallback} (${resp.status})`,
    resp.status,
  );
}

async function authed(path: string, init?: RequestInit): Promise<Response> {
  const token = getToken();
  if (!token) throw new Error("Not signed in");
  return fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  });
}

/**
 * Start a search. Throws `ApiError` — `quota_exhausted` (402),
 * `monthly_cap` (429) and `search_in_progress` (409) are all expected answers
 * here, not bugs, and the caller can tell them apart by `code`.
 */
export async function createSearch(params: SearchParams): Promise<string> {
  const resp = await authed("/searches", {
    method: "POST",
    body: JSON.stringify(params),
  });
  if (!resp.ok) await fail(resp, "Couldn't start that search");
  const data = await resp.json();
  return data.search_id;
}

/** Limits come from the server so raising them needs no frontend change. */
export async function getConfig(): Promise<AppConfig> {
  const resp = await fetch(`${API_URL}/config`);
  if (!resp.ok) throw new Error(`config failed: ${resp.status}`);
  return resp.json();
}

/** Ask the LLM to turn a free-text description into role suggestions. Free (no quota). */
export async function interpretRoles(
  text: string,
): Promise<{
  roles: RoleSuggestion[];
  ok: boolean;
  message: string;
  max_roles: number;
}> {
  const resp = await authed("/roles/interpret", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) await fail(resp, "Couldn't work out what you're looking for");
  return resp.json();
}

/** Recent searches for the workspace rail. Newest first. */
export async function listSearches(limit = 10): Promise<SearchSummary[]> {
  const resp = await authed(`/searches?limit=${limit}`);
  if (!resp.ok) await fail(resp, "Couldn't load your recent searches");
  const data = await resp.json();
  return data.searches;
}

/** Halt a running search. 409 if it already finished. */
export async function stopSearch(searchId: string): Promise<void> {
  const resp = await authed(`/searches/${searchId}/stop`, { method: "POST" });
  if (!resp.ok) await fail(resp, "Couldn't stop this search");
}

export async function getSearch(searchId: string): Promise<Search> {
  const resp = await authed(`/searches/${searchId}`);
  if (!resp.ok) await fail(resp, "Couldn't load that search");
  return resp.json();
}
