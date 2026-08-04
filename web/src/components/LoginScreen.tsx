"use client";

import Image from "next/image";
import { useState } from "react";
import { login } from "@/lib/auth";
import StreetMapBackdrop from "./StreetMapBackdrop";
import { Button, Card } from "./ui";

/**
 * Google's brand mark. The four hex values are Google's own brand colours and
 * their sign-in branding guidelines require them exactly — they are deliberately
 * not tokens, and are the only literal colours in a component.
 */
function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.52 12.27c0-.85-.08-1.67-.22-2.45H12v4.63h6.46a5.52 5.52 0 0 1-2.4 3.62v3h3.88c2.27-2.09 3.58-5.17 3.58-8.8Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.08 7.94-2.93l-3.88-3a7.2 7.2 0 0 1-10.72-3.78H1.34v3.09A12 12 0 0 0 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.34 14.29a7.19 7.19 0 0 1 0-4.58V6.62H1.34a12 12 0 0 0 0 10.76l4-3.09Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.44-3.44C17.95 1.19 15.24 0 12 0A12 12 0 0 0 1.34 6.62l4 3.09A7.2 7.2 0 0 1 12 4.75Z"
      />
    </svg>
  );
}

export default function LoginScreen() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signIn = async () => {
    setBusy(true);
    setError(null);
    try {
      await login();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden px-5 py-10">
      <StreetMapBackdrop />

      <Card
        tone="plain"
        elevated
        className="relative w-full max-w-[360px] px-8 py-10 text-center"
      >
        <Image
          src="/logo.png"
          alt=""
          width={56}
          height={56}
          priority
          className="mx-auto mb-4 h-14 w-14 object-contain"
        />
        <h1 className="m-0 mb-1.5 text-xl font-extrabold text-ink">
          Find Me a Job AI
        </h1>
        <p className="m-0 mb-7 text-[13px] leading-normal text-slate-muted">
          Your next job, found street by street.
        </p>

        <Button
          variant="secondary"
          block
          onClick={signIn}
          disabled={busy}
          aria-label="Continue with Google"
        >
          <GoogleMark />
          {busy ? "Redirecting…" : "Continue with Google"}
        </Button>

        {error && (
          <p role="alert" className="mt-3 mb-0 text-[13px] text-pin">
            {error}
          </p>
        )}

        <p className="mt-[18px] mb-0 text-[11px] leading-normal text-slate-muted">
          By continuing, you agree to our{" "}
          <a href="/terms" className="underline underline-offset-2">
            Terms
          </a>{" "}
          and{" "}
          <a href="/privacy" className="underline underline-offset-2">
            Privacy Policy
          </a>
          .
        </p>
      </Card>
    </main>
  );
}
