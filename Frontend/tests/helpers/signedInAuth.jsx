/**
 * Stand-in for src/context/AuthContext that is always signed in. The
 * analysis workflow requires a logged-in user, so tests about the workflow
 * itself use this instead of driving a real login:
 *
 *   vi.mock("../src/context/AuthContext", () => import("./helpers/signedInAuth.jsx"));
 *
 * Login, logout and the logged-out redirect are tested for real in
 * Auth.test.jsx against the actual AuthContext.
 */
export const TEST_USER = {
  id: "test-user-id",
  name: "Test User",
  username: "test_user",
  email: "test@example.com",
  profile_picture: null,
  created_at: "2026-10-01T12:00:00.000Z",
  updated_at: "2026-10-01T12:00:00.000Z",
  is_active: true,
};

const value = {
  status: "authenticated",
  user: TEST_USER,
  login: async () => TEST_USER,
  register: async () => TEST_USER,
  logout: async () => {},
  loadProfile: async () => TEST_USER,
  getAccessToken: async () => "test-access-token",
};

export function AuthProvider({ children }) {
  return children;
}

export function useAuth() {
  return value;
}
