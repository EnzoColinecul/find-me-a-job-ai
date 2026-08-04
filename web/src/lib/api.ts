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
}

export interface Search {
  search_id: string;
  status: "pending" | "running" | "completed" | "failed";
  /** Roles come back as plain labels here, not RoleSpecs. */
  params: Omit<SearchParams, "roles"> & { roles: string[] };
  results: SearchResult[];
  total: number;
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

/** Start a search. Throws Error with a friendly message on 402 (quota). */
export async function createSearch(params: SearchParams): Promise<string> {
  const resp = await authed("/searches", {
    method: "POST",
    body: JSON.stringify(params),
  });
  if (resp.status === 402) {
    const body = await resp.json().catch(() => null);
    throw new Error(body?.detail ?? "Free search already used");
  }
  if (!resp.ok) throw new Error(`Search failed: ${resp.status}`);
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
  if (!resp.ok) throw new Error(`Could not interpret that: ${resp.status}`);
  return resp.json();
}

/** Recent searches for the workspace rail. Newest first. */
export async function listSearches(limit = 10): Promise<SearchSummary[]> {
  const resp = await authed(`/searches?limit=${limit}`);
  if (!resp.ok) throw new Error(`listSearches failed: ${resp.status}`);
  const data = await resp.json();
  return data.searches;
}

export async function getSearch(searchId: string): Promise<Search> {
  const resp = await authed(`/searches/${searchId}`);
  if (!resp.ok) throw new Error(`getSearch failed: ${resp.status}`);
  return resp.json();
}
