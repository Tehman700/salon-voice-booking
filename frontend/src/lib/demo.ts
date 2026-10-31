/** One-click sign-in shortcuts shown on the login page in local/demo setups. */
export const MOCKS_ENABLED = process.env.NEXT_PUBLIC_API_MOCKS === "true";

type DemoLogin = { label: string; email: string; password: string };

const MOCK_LOGINS: DemoLogin[] = [
  { label: "Owner (2 salons)", email: "owner@lumiere.pk", password: "demo-password" },
  { label: "Staff", email: "sana@lumiere.pk", password: "demo-password" },
  { label: "Owner (1 salon)", email: "owner@studionoor.pk", password: "demo-password" },
];

// Created by `uv run python -m app.scripts.seed` against the real backend.
const BACKEND_LOGINS: DemoLogin[] = [
  { label: "Owner", email: "owner@demo.example.com", password: "demo-password-123" },
  { label: "Manager", email: "manager@demo.example.com", password: "demo-password-123" },
  { label: "Staff", email: "staff@demo.example.com", password: "demo-password-123" },
];

export const DEMO_LOGINS: DemoLogin[] =
  process.env.NODE_ENV === "production" && !MOCKS_ENABLED ? [] : MOCKS_ENABLED ? MOCK_LOGINS : BACKEND_LOGINS;
