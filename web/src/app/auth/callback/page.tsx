"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { handleCallback } from "@/lib/auth";

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = params.get("code");
    const oauthError = params.get("error");
    if (oauthError) {
      setError(oauthError);
      return;
    }
    if (!code) {
      setError("Missing authorization code");
      return;
    }
    handleCallback(code)
      .then(() => router.replace("/"))
      .catch((e) => setError(String(e)));
  }, [params, router]);

  return error ? (
    <>
      <h1>Sign-in failed</h1>
      <p style={{ color: "crimson" }}>{error}</p>
      <a href="/">Back to start</a>
    </>
  ) : (
    <p>Signing you in…</p>
  );
}

export default function AuthCallback() {
  return (
    <main style={{ maxWidth: 640, margin: "4rem auto", padding: "0 1rem" }}>
      <Suspense fallback={<p>Signing you in…</p>}>
        <CallbackInner />
      </Suspense>
    </main>
  );
}
