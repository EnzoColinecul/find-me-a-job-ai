"use client";

import { useEffect, useState } from "react";
import {
  getConfig,
  getMe,
  interpretRoles,
  type AppConfig,
  type Me,
  type RoleSuggestion,
} from "@/lib/api";
import LoginScreen from "@/components/LoginScreen";
import HomeScreen from "@/components/HomeScreen";
import Workspace from "@/components/Workspace";

/**
 * The three states of the front door:
 *   signed out          → login (map hero)
 *   signed in, no roles → home (conversational opening)
 *   roles interpreted   → workspace (three panes)
 */
export default function Home() {
  const [me, setMe] = useState<Me | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);

  const [suggestions, setSuggestions] = useState<RoleSuggestion[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [interpreting, setInterpreting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
    getConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  const maxRoles = config?.max_roles ?? 1;

  const interpret = async (text: string) => {
    setInterpreting(true);
    setError(null);
    try {
      const res = await interpretRoles(text);
      if (!res.ok || res.roles.length === 0) {
        // Don't fabricate a role out of their sentence — ask them to rephrase.
        setError(res.message || "Please try describing the work differently.");
        return;
      }
      setSuggestions(res.roles);
      setSelected(res.roles.slice(0, res.max_roles).map((r) => r.label));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInterpreting(false);
    }
  };

  const toggleRole = (label: string) => {
    setSelected((prev) => {
      if (prev.includes(label)) return prev.filter((r) => r !== label);
      if (prev.length >= maxRoles) {
        // At the cap: replace the oldest, so a single-role plan feels like
        // "pick one" rather than a silently ignored tap.
        return maxRoles === 1 ? [label] : [...prev.slice(1), label];
      }
      return [...prev, label];
    });
  };

  const addRole = (label: string) => {
    setSuggestions((prev) => {
      const list = prev ?? [];
      return list.some((r) => r.label === label)
        ? list
        : [...list, { label, curated_key: label, why: "You picked this one." }];
    });
    toggleRole(label);
  };

  const startOver = () => {
    setSuggestions(null);
    setSelected([]);
    setError(null);
  };

  if (loading) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4">
        <p className="text-sm text-slate-muted">Loading…</p>
      </main>
    );
  }

  if (!me) return <LoginScreen />;

  if (!suggestions) {
    return (
      <HomeScreen
        firstName={me.name ? me.name.split(" ")[0] : null}
        busy={interpreting}
        error={error}
        onSubmit={interpret}
      />
    );
  }

  return (
    <Workspace
      me={me}
      config={config}
      suggestions={suggestions}
      selected={selected}
      onToggleRole={toggleRole}
      onAddRole={addRole}
      onStartOver={startOver}
    />
  );
}
