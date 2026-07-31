// Lightweight Cognito hosted-UI login with PKCE (public SPA client, no secret).
// Flow: login() -> Cognito hosted UI -> Google -> /auth/callback?code=... -> exchange -> tokens.

const DOMAIN = process.env.NEXT_PUBLIC_COGNITO_DOMAIN!; // https://fmaj-test.auth....amazoncognito.com
const CLIENT_ID = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!;
const REDIRECT_URI =
  typeof window !== "undefined" ? `${window.location.origin}/auth/callback` : "";

const TOKEN_KEY = "fmaj_id_token";
const VERIFIER_KEY = "fmaj_pkce_verifier";

function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function sha256(input: string): Promise<Uint8Array> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return new Uint8Array(digest);
}

function randomVerifier(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

/** Redirect to the Cognito hosted UI, going straight to Google. */
export async function login(): Promise<void> {
  const verifier = randomVerifier();
  const challenge = base64url(await sha256(verifier));
  sessionStorage.setItem(VERIFIER_KEY, verifier);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    scope: "openid email profile",
    identity_provider: "Google",
    code_challenge_method: "S256",
    code_challenge: challenge,
  });
  window.location.href = `${DOMAIN}/oauth2/authorize?${params}`;
}

/** Exchange the ?code for tokens. Call on the /auth/callback page. */
export async function handleCallback(code: string): Promise<void> {
  const verifier = sessionStorage.getItem(VERIFIER_KEY) ?? "";
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    code,
    redirect_uri: REDIRECT_URI,
    code_verifier: verifier,
  });
  const resp = await fetch(`${DOMAIN}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!resp.ok) throw new Error(`Token exchange failed: ${resp.status}`);
  const data = await resp.json();
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.setItem(TOKEN_KEY, data.id_token);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

export function logout(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    logout_uri: window.location.origin,
  });
  window.location.href = `${DOMAIN}/logout?${params}`;
}
