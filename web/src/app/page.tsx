"use client";

import { useEffect, useState } from "react";
import { login, logout } from "@/lib/auth";
import { getMe, type Me } from "@/lib/api";
import SearchForm from "@/components/SearchForm";

export default function Home() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main style={{ maxWidth: 640, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>Find-Me-A-Job AI</h1>
      <p>
        Pick a location, a radius and a role — we investigate every nearby company
        for job opportunities.
      </p>

      {loading ? (
        <p style={{ color: "#888" }}>Loading…</p>
      ) : me ? (
        <div>
          <p>
            Signed in as <strong>{me.name || me.email}</strong>
            {me.free_search_used ? " · free search used" : " · 1 free search available"}
            {" · "}
            <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>
              sign out
            </a>
          </p>
          <SearchForm />
        </div>
      ) : (
        <button onClick={() => login()}>Sign in with Google</button>
      )}
    </main>
  );
}
