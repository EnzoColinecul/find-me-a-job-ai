"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { logout } from "@/lib/auth";
import { getMe, type Me } from "@/lib/api";
import SearchForm from "@/components/SearchForm";
import LoginScreen from "@/components/LoginScreen";
import { Button } from "@/components/ui";

export default function Home() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-160 items-center justify-center px-4">
        <p className="text-sm text-slate-muted">Loading…</p>
      </main>
    );
  }

  if (!me) return <LoginScreen />;

  // TODO(Phase 5): the three-pane workspace replaces this single-column shell.
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-200 items-center gap-3 px-4 py-3">
          <Image
            src="/logo.png"
            alt=""
            width={32}
            height={32}
            priority
            className="h-8 w-8 object-contain"
          />
          <span className="text-sm font-bold text-ink">Find Me a Job AI</span>
          <span className="ml-auto text-[13px] text-slate-muted">
            {me.name || me.email}
            {me.free_search_used ? " · free search used" : " · 1 free search left"}
          </span>
          <Button variant="ghost" size="sm" onClick={() => logout()}>
            Sign out
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-200 px-4 py-10">
        <h1 className="m-0 mb-1.5 text-2xl font-extrabold text-ink">
          {me.name ? `Hello ${me.name.split(" ")[0]}` : "Hello"} — what role do you
          want next?
        </h1>
        <p className="m-0 mb-7 text-sm text-slate-muted">
          Tell me a little about your experience too, and I&apos;ll search the
          streets around you.
        </p>
        <SearchForm />
      </main>
    </div>
  );
}
