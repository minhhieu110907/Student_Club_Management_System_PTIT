const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

global.location = { origin: "http://localhost:8080" };

const auth = require("./app.js");

function response(status, body = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
}

function domNode() {
  return {
    classList: { add() {}, remove() {}, toggle() {} },
    className: "",
    focusOptions: null,
    setAttribute(name, value) {
      this[name] = value;
    },
    focus(options) {
      this.focusOptions = options;
    },
    textContent: "",
    type: "password",
  };
}

function installDom() {
  const nodes = new Map([
    ["#admin-message", domNode()],
    ["#admin-view", domNode()],
    ["#login-message", domNode()],
    ["#login-password", domNode()],
    ["#login-view", domNode()],
    ["#password-toggle", domNode()],
    ["#request-list", domNode()],
    ["#club-list", domNode()],
    ["#admin-list", domNode()],
    ["#session-summary", domNode()],
    ["#student-message", domNode()],
    ["#student-view", domNode()],
    ["[data-password-icon='eye']", domNode()],
    ["[data-password-icon='eye-off']", domNode()],
  ]);
  global.document = { querySelector: (selector) => nodes.get(selector) };
  return nodes;
}

test.afterEach(() => {
  auth.invalidateSession();
  auth.state.user = null;
  delete global.document;
  delete global.fetch;
  delete global.FormData;
});

test("two concurrent 401 responses share one refresh and retry with the new token", async () => {
  auth.replaceSession("old-token");
  const refresh = deferred();
  let refreshCalls = 0;
  const authorizations = [];
  global.fetch = async (url, options = {}) => {
    if (url === "/api/v1/auth/refresh") {
      refreshCalls += 1;
      return refresh.promise;
    }
    authorizations.push(options.headers.Authorization);
    if (options.headers.Authorization === "Bearer old-token")
      return response(401, { message: "Unauthorized" });
    return response(200, { path: url });
  };

  const requests = Promise.all([auth.api("/one"), auth.api("/two")]);
  await Promise.resolve();
  assert.equal(refreshCalls, 1);
  refresh.resolve(response(200, { access_token: "new-token" }));

  assert.deepEqual(await requests, [{ path: "/one" }, { path: "/two" }]);
  assert.deepEqual(authorizations, [
    "Bearer old-token",
    "Bearer old-token",
    "Bearer new-token",
    "Bearer new-token",
  ]);
  assert.equal(refreshCalls, 1);
});

test("a delayed 401 for the old token retries with the installed token without refreshing again", async () => {
  auth.replaceSession("old-token");
  const delayed = deferred();
  let refreshCalls = 0;
  const authorizations = [];
  global.fetch = async (url, options = {}) => {
    if (url === "/api/v1/auth/refresh") {
      refreshCalls += 1;
      return response(200, { access_token: "new-token" });
    }
    authorizations.push(`${url}:${options.headers.Authorization}`);
    if (url === "/slow" && options.headers.Authorization === "Bearer old-token")
      return delayed.promise;
    if (options.headers.Authorization === "Bearer old-token")
      return response(401, { message: "Unauthorized" });
    return response(200, { path: url });
  };

  const slow = auth.api("/slow");
  assert.deepEqual(await auth.api("/fast"), { path: "/fast" });
  delayed.resolve(response(401, { message: "Unauthorized" }));
  assert.deepEqual(await slow, { path: "/slow" });
  assert.equal(refreshCalls, 1);
  assert.deepEqual(authorizations, [
    "/slow:Bearer old-token",
    "/fast:Bearer old-token",
    "/fast:Bearer new-token",
    "/slow:Bearer new-token",
  ]);
});

test("refresh failure stops after one attempt", async () => {
  auth.replaceSession("expired-token");
  let apiCalls = 0;
  let refreshCalls = 0;
  global.fetch = async (url) => {
    if (url === "/api/v1/auth/refresh") {
      refreshCalls += 1;
      return response(401, { message: "Refresh rejected" });
    }
    apiCalls += 1;
    return response(401, { message: "Unauthorized" });
  };

  await assert.rejects(auth.api("/protected"), /Unauthorized/);
  assert.equal(apiCalls, 1);
  assert.equal(refreshCalls, 1);
});

test("refresh network failure stops after one attempt", async () => {
  auth.replaceSession("expired-token");
  let apiCalls = 0;
  let refreshCalls = 0;
  global.fetch = async (url) => {
    if (url === "/api/v1/auth/refresh") {
      refreshCalls += 1;
      throw new TypeError("Network unavailable");
    }
    apiCalls += 1;
    return response(401, { message: "Unauthorized" });
  };

  await assert.rejects(auth.api("/protected"), /Unauthorized/);
  assert.equal(apiCalls, 1);
  assert.equal(refreshCalls, 1);
});

test("a refresh completing after successful logout cannot restore credentials", async () => {
  const nodes = installDom();
  auth.replaceSession("old-token");
  auth.state.user = { global_role: "STUDENT" };
  const refresh = deferred();
  global.fetch = async (url) => {
    if (url === "/api/v1/auth/refresh") return refresh.promise;
    if (url === "/api/v1/auth/logout") return response(204);
    throw new Error(`Unexpected URL: ${url}`);
  };

  const staleRefresh = auth.refreshAccessToken();
  await auth.logout();
  refresh.resolve(response(200, { access_token: "stale-token" }));

  assert.equal(await staleRefresh, false);
  assert.equal(auth.state.accessToken, null);
  assert.equal(nodes.get("#session-summary").textContent, "Signed out");
});

test("a replacement login session cannot be overwritten by an older refresh", async () => {
  auth.replaceSession("old-token");
  const refresh = deferred();
  global.fetch = async () => refresh.promise;

  const staleRefresh = auth.refreshAccessToken();
  auth.replaceSession("login-token");
  refresh.resolve(response(200, { access_token: "stale-token" }));

  assert.equal(await staleRefresh, false);
  assert.equal(auth.state.accessToken, "login-token");
});

test("a replacement session can start its own refresh while an old refresh is pending", async () => {
  auth.replaceSession("old-token");
  const oldRefresh = deferred();
  let refreshCalls = 0;
  global.fetch = async () => {
    refreshCalls += 1;
    if (refreshCalls === 1) return oldRefresh.promise;
    return response(200, { access_token: "replacement-refreshed-token" });
  };

  const staleRefresh = auth.refreshAccessToken();
  auth.replaceSession("login-token");
  assert.equal(await auth.refreshAccessToken(), true);
  oldRefresh.resolve(response(200, { access_token: "stale-token" }));

  assert.equal(await staleRefresh, false);
  assert.equal(auth.state.accessToken, "replacement-refreshed-token");
  assert.equal(refreshCalls, 2);
});

test("a request from a replaced session is not retried with the replacement login", async () => {
  auth.replaceSession("old-token");
  const oldRequest = deferred();
  let refreshCalls = 0;
  let protectedCalls = 0;
  global.fetch = async (url) => {
    if (url === "/api/v1/auth/refresh") {
      refreshCalls += 1;
      return response(200, { access_token: "unexpected-token" });
    }
    protectedCalls += 1;
    return oldRequest.promise;
  };

  const staleRequest = auth.api("/protected");
  auth.replaceSession("login-token");
  oldRequest.resolve(response(401, { message: "Unauthorized" }));

  await assert.rejects(staleRequest, /Unauthorized/);
  assert.equal(auth.state.accessToken, "login-token");
  assert.equal(protectedCalls, 1);
  assert.equal(refreshCalls, 0);
});

test("student data delayed past logout cannot render into the signed-out UI", async () => {
  const nodes = installDom();
  auth.replaceSession("student-token");
  auth.state.user = { global_role: "STUDENT" };
  nodes.get("#request-list").innerHTML = "current requests";
  nodes.get("#club-list").innerHTML = "current clubs";
  const delayed = deferred();
  global.fetch = async (url) => {
    const payloads = await delayed.promise;
    return response(200, payloads[url]);
  };

  const staleLoad = auth.loadStudent();
  auth.invalidateSession();
  delayed.resolve({
    "/api/v1/club-requests/mine": [{ proposed_name: "Old request" }],
    "/api/v1/clubs/mine": [{ name: "Old club" }],
  });
  await staleLoad;

  assert.equal(nodes.get("#request-list").innerHTML, "current requests");
  assert.equal(nodes.get("#club-list").innerHTML, "current clubs");
});

test("admin data from a previous account cannot render after account replacement", async () => {
  const nodes = installDom();
  auth.replaceSession("admin-token");
  auth.state.user = { global_role: "ADMIN" };
  nodes.get("#admin-list").innerHTML = "replacement account data";
  const delayed = deferred();
  global.fetch = async () => delayed.promise;

  const staleLoad = auth.loadAdmin();
  auth.replaceSession("replacement-token");
  delayed.resolve(response(200, [{ proposed_name: "Previous account request" }]));
  await staleLoad;

  assert.equal(nodes.get("#admin-list").innerHTML, "replacement account data");
});

test("a stale data-loading error cannot overwrite the replacement session message", async () => {
  const nodes = installDom();
  auth.replaceSession("student-token");
  auth.state.user = { global_role: "STUDENT" };
  nodes.get("#student-message").textContent = "replacement session message";
  const delayed = deferred();
  global.fetch = async () => delayed.promise;

  const staleLoad = auth.loadSessionData();
  auth.replaceSession("replacement-token");
  delayed.reject(new Error("old session failure"));
  await staleLoad;

  assert.equal(nodes.get("#student-message").textContent, "replacement session message");
});

test("a completed club submission cannot affect a replacement session", async () => {
  const nodes = installDom();
  auth.replaceSession("student-token");
  auth.state.user = { global_role: "STUDENT" };
  const mutation = deferred();
  let fetchCalls = 0;
  let resetCalls = 0;
  global.FormData = class {
    *[Symbol.iterator]() {
      yield ["proposed_name", "Previous session proposal"];
    }
  };
  global.fetch = async () => {
    fetchCalls += 1;
    return mutation.promise;
  };
  const form = {
    reset() {
      resetCalls += 1;
    },
  };

  const submission = auth.submitClubRequest({
    currentTarget: form,
    preventDefault() {},
  });
  auth.replaceSession("replacement-token");
  nodes.get("#student-message").textContent = "replacement session message";
  mutation.resolve(response(201, { id: 42 }));
  await submission;

  assert.equal(fetchCalls, 1);
  assert.equal(resetCalls, 0);
  assert.equal(nodes.get("#student-message").textContent, "replacement session message");
});

test("a failed admin decision cannot affect a replacement session", async () => {
  const nodes = installDom();
  auth.replaceSession("admin-token");
  auth.state.user = { global_role: "ADMIN" };
  const mutation = deferred();
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    return mutation.promise;
  };
  const button = {
    dataset: { action: "approve", id: "17" },
    disabled: false,
  };

  const decision = auth.reviewClubRequest({
    target: { closest: () => button },
  });
  assert.equal(button.disabled, true);
  auth.replaceSession("replacement-token");
  nodes.get("#admin-message").textContent = "replacement session message";
  mutation.reject(new Error("previous session failure"));
  await decision;

  assert.equal(fetchCalls, 1);
  assert.equal(button.disabled, true);
  assert.equal(nodes.get("#admin-message").textContent, "replacement session message");
});

test("password visibility remains accessible and focus preserving", () => {
  const nodes = installDom();
  const input = nodes.get("#login-password");
  const toggle = nodes.get("#password-toggle");

  auth.setPasswordVisibility(true);
  assert.equal(input.type, "text");
  assert.equal(toggle["aria-label"], "Hide password");
  assert.equal(toggle["aria-pressed"], "true");
  assert.deepEqual(input.focusOptions, { preventScroll: true });

  auth.setPasswordVisibility(false);
  assert.equal(input.type, "password");
  assert.equal(toggle["aria-label"], "Show password");
  assert.equal(toggle["aria-pressed"], "false");
});

test("authentication and club endpoint paths remain unchanged", () => {
  const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  for (const endpoint of [
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
    "/api/v1/auth/refresh",
    "/api/v1/club-requests",
    "/api/v1/club-requests/mine",
    "/api/v1/clubs/mine",
    "/api/v1/admin/club-requests/pending",
  ])
    assert.match(source, new RegExp(endpoint.replaceAll("/", "\\/")));
});
