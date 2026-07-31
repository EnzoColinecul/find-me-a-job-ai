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
