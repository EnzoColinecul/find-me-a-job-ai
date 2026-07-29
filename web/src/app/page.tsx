export default function Home() {
  return (
    <main style={{ maxWidth: 640, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>Find-Me-A-Job AI</h1>
      <p>
        Pick a location, a radius and a role — we investigate every nearby company
        for job opportunities.
      </p>
      {/* TODO(Phase 1): map (MapLibre/Google), radius selector, role combobox,
          Cognito Google login, POST /searches */}
      <p style={{ color: "#888" }}>Scaffold — Phase 1 in progress.</p>
    </main>
  );
}
