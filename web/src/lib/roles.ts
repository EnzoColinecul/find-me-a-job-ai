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

export const MAX_ROLES = 3;
export const RADIUS_OPTIONS_KM = [1, 5, 10] as const;
