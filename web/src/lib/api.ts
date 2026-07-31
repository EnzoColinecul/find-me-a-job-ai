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

export interface SearchParams {
  lat: number;
  lng: number;
  radius_km: number;
  roles: string[];
}

export interface SearchResult {
  place_id: string;
  company: string;
  address: string;
  opportunity_type: string;
  links: string[];
  emails: string[];
}

export interface Search {
  search_id: string;
  status: "pending" | "running" | "completed" | "failed";
  params: SearchParams;
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

export async function getSearch(searchId: string): Promise<Search> {
  const resp = await authed(`/searches/${searchId}`);
  if (!resp.ok) throw new Error(`getSearch failed: ${resp.status}`);
  return resp.json();
}
