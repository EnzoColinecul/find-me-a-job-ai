"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { handleCallback } from "@/lib/auth";
import { Card } from "@/components/ui";

function Signing() {
  return <p className="m-0 text-sm text-slate-muted">Signing you in…</p>;
}

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
      <h1 className="m-0 mb-2 text-lg font-bold text-ink">Sign-in failed</h1>
      <p role="alert" className="m-0 mb-4 text-sm text-pin">
        {error}
      </p>
      <Link href="/" className="text-sm font-semibold">
        Back to start
      </Link>
    </>
  ) : (
    <Signing />
  );
}

export default function AuthCallback() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-5">
      <Card className="w-full max-w-100 px-7 py-8 text-center">
        <Suspense fallback={<Signing />}>
          <CallbackInner />
        </Suspense>
      </Card>
    </main>
  );
}
