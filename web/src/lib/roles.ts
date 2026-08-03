// Curated AU roles for V1 (mirrors the role→Places-type mapping the backend will use).
export const CURATED_ROLES = [
  "chef",
  "kitchen hand",
  "barista",
  "waiter / waitress",
  "bartender",
  "retail assistant",
  "supermarket assistant",
  "construction labourer",
  "electrician",
  "plumber",
  "cleaner",
  "receptionist",
  "hairdresser / barber",
  "aged care worker",
  "it support",
] as const;

// Limits live on the server (GET /config) so they can change without a frontend
// release — see api/app/settings.py (max_roles, max_radius_km).
