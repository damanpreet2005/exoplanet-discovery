/**
 * Analysis routes require a signed-in user. Tests that exercise those routes
 * (not the account system itself -- see auth.test.js) use this app, whose
 * auth service accepts exactly one fixed test token.
 */
const request = require("supertest");
const { createApp } = require("../../src/app");
const { AuthenticationError } = require("../../src/errors");

const TEST_TOKEN = "test-access-token";
const TEST_USER = { _id: "test-user-id", name: "Test User", username: "test_user", email: "test@example.com", is_active: true };

function createAuthedApp() {
  const service = {
    async authenticate(token) {
      if (token !== TEST_TOKEN) throw new AuthenticationError("Invalid or expired access token.", "INVALID_TOKEN");
      return { user: TEST_USER, claims: { sub: TEST_USER._id, sid: "test-session" } };
    },
    toPublicUser: (user) => ({ id: user._id, name: user.name, username: user.username, email: user.email }),
  };
  return createApp({ auth: { service } });
}

/** A supertest agent that sends the test token on every request. */
function authedAgent(app) {
  return request.agent(app).set("Authorization", `Bearer ${TEST_TOKEN}`);
}

module.exports = { createAuthedApp, authedAgent, TEST_TOKEN };
