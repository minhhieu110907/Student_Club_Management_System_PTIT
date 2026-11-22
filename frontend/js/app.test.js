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
    ["#discovery-list", domNode()],
    ["#manager-membership-list", domNode()],
    ["#manager-message", domNode()],
    ["#manager-panel", domNode()],
    ["#membership-application-list", domNode()],
    ["#membership-list", domNode()],
    ["#admin-list", domNode()],
    ["#session-summary", domNode()],
    ["#student-message", domNode()],
    ["#student-view", domNode()],
    ["#events-list", domNode()],
    ["#events-pagination", domNode()],
    ["#my-registrations-list", domNode()],
    ["#my-registrations-pagination", domNode()],
    ["#events-message", domNode()],
    ["#event-detail-panel", domNode()],
    ["#event-create-form", domNode()],
    ["#event-submit-btn", domNode()],
    ["#event-edit-cancel", domNode()],
    ["#manager-events-panel", domNode()],
    ["#manager-events-list", domNode()],
    ["#manager-events-pagination", domNode()],
    ["#manager-participants-list", domNode()],
    ["#manager-participants-pagination", domNode()],
    ["#manager-events-message", domNode()],
    ["#event-club-select", domNode()],
    ["#my-tasks-list", domNode()],
    ["#my-tasks-pagination", domNode()],
    ["#my-tasks-message", domNode()],
    ["#manager-tasks-panel", domNode()],
    ["#manager-tasks-event-title", domNode()],
    ["#manager-task-progress", domNode()],
    ["#task-create-form", domNode()],
    ["#task-assignee-select", domNode()],
    ["#task-submit-btn", domNode()],
    ["#task-edit-cancel", domNode()],
    ["#manager-tasks-list", domNode()],
    ["#manager-tasks-pagination", domNode()],
    ["#manager-tasks-message", domNode()],
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

test("a completed membership application cannot affect a replacement session", async () => {
  const nodes = installDom();
  auth.replaceSession("student-token");
  auth.state.user = { global_role: "STUDENT" };
  const mutation = deferred();
  let disabled = false;
  global.FormData = class {
    get() {
      return "Learn backend";
    }
  };
  global.fetch = async () => mutation.promise;
  const form = {
    dataset: { clubId: "11" },
    querySelector() {
      return {
        set disabled(value) {
          disabled = value;
        },
      };
    },
  };

  const submission = auth.submitMembershipApplication({
    preventDefault() {},
    target: { closest: () => form },
  });
  auth.replaceSession("replacement-token");
  nodes.get("#student-message").textContent = "replacement session message";
  mutation.resolve(response(201, { id: 42 }));
  await submission;

  assert.equal(disabled, true);
  assert.equal(nodes.get("#student-message").textContent, "replacement session message");
});

test("a completed leave cannot affect a replacement session", async () => {
  const nodes = installDom();
  auth.replaceSession("student-token");
  auth.state.user = { global_role: "STUDENT" };
  const mutation = deferred();
  global.window = { confirm: () => true };
  global.fetch = async () => mutation.promise;
  const button = { dataset: { leaveMembership: "31" }, disabled: false };

  const leaving = auth.leaveClub({ target: { closest: () => button } });
  auth.replaceSession("replacement-token");
  nodes.get("#student-message").textContent = "replacement session message";
  mutation.resolve(response(200, { status: "LEFT" }));
  await leaving;

  assert.equal(button.disabled, true);
  assert.equal(nodes.get("#student-message").textContent, "replacement session message");
  delete global.window;
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
    "/api/v1/clubs",
    "/api/v1/membership-applications/mine",
    "/api/v1/memberships/mine",
    "/membership-applications/pending",
    "/api/v1/membership-applications/",
    "/api/v1/memberships/",
    "/api/v1/events",
    "/api/v1/event-registrations/mine",
    "/registrations/me",
  ])
    assert.match(source, new RegExp(endpoint.replaceAll("/", "\\/")));
});

test("events workspace escapes untrusted titles and renders registration controls", async () => {
  const nodes = installDom();
  global.document.createElement = () => ({
    _text: "",
    set textContent(value) {
      this._text = String(value);
    },
    get innerHTML() {
      return this._text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    },
  });
  auth.replaceSession("valid-token");
  global.fetch = async (url) => {
    if (url.startsWith("/api/v1/events?")) {
      return response(200, {
        items: [
          {
            id: 7,
            club_id: 1,
            club_name: "Robotics <Club>",
            title: "<script>alert(1)</script>",
            visibility: "PUBLIC_STUDENTS",
            location: "Hall A",
            starts_at: "2026-12-01T10:00:00Z",
            capacity: 10,
            registration_count: 3,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      });
    }
    if (url.startsWith("/api/v1/event-registrations/mine")) {
      return response(200, { items: [], total: 0, page: 1, page_size: 20 });
    }
    return response(200, { items: [], total: 0, page: 1, page_size: 20 });
  };

  await auth.loadEventsWorkspace([], auth.state.generation);
  const eventsHtml = nodes.get("#events-list").innerHTML;
  assert.ok(!eventsHtml.includes("<script>alert(1)</script>"));
  assert.ok(eventsHtml.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(eventsHtml.includes('data-event-register="7"'));
});

test("events workspace uses backend is_registered flag and renders pagination", async () => {
  const nodes = installDom();
  global.document.createElement = () => ({
    _text: "",
    set textContent(value) {
      this._text = String(value);
    },
    get innerHTML() {
      return this._text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    },
  });
  auth.replaceSession("valid-token");
  global.fetch = async (url) => {
    if (url.startsWith("/api/v1/events?")) {
      return response(200, {
        items: [
          {
            id: 99,
            club_id: 1,
            club_name: "Robotics",
            title: "Deep Tech",
            visibility: "PUBLIC_STUDENTS",
            location: "Hall B",
            starts_at: "2026-12-01T10:00:00Z",
            capacity: 10,
            registration_count: 10,
            is_registered: true,
          },
        ],
        total: 25,
        page: 1,
        page_size: 20,
      });
    }
    return response(200, { items: [], total: 0, page: 1, page_size: 20 });
  };

  await auth.loadEventsWorkspace([], auth.state.generation);
  const eventsHtml = nodes.get("#events-list").innerHTML;
  assert.ok(eventsHtml.includes('data-event-cancel-reg="99"'));
  const paginationHtml = nodes.get("#events-pagination").innerHTML;
  assert.ok(paginationHtml.includes("Page 1 of 2"));
});

test("edit event mode restricts PUBLISHED fields and sends PATCH payload", async () => {
  const nodes = installDom();
  const fields = {
    club_id: { value: "1", disabled: false },
    title: { value: "", disabled: false },
    location: { value: "", disabled: false },
    description: { value: "", disabled: false },
    visibility: { value: "PUBLIC_STUDENTS", disabled: false },
    capacity: { value: "10", disabled: false },
    starts_at: { value: "", disabled: false },
    ends_at: { value: "", disabled: false },
    registration_opens_at: { value: "", disabled: false },
    registration_closes_at: { value: "", disabled: false },
    cancellation_deadline_at: { value: "", disabled: false },
  };
  const form = nodes.get("#event-create-form");
  form.elements = fields;
  form.reset = () => {};

  auth.replaceSession("valid-token");
  auth.setEventFormMode({
    id: 12,
    club_id: 1,
    status: "PUBLISHED",
    title: "Published Talk",
    location: "Room 1",
    description: "Desc",
    visibility: "PUBLIC_STUDENTS",
    capacity: 15,
    starts_at: "2026-12-05T10:00:00Z",
    ends_at: "2026-12-05T12:00:00Z",
    registration_opens_at: "2026-12-01T10:00:00Z",
    registration_closes_at: "2026-12-04T10:00:00Z",
    cancellation_deadline_at: null,
  });

  assert.equal(fields.club_id.disabled, true);
  assert.equal(fields.visibility.disabled, true);
  assert.equal(fields.starts_at.disabled, true);
  assert.equal(fields.ends_at.disabled, true);
  assert.equal(fields.registration_opens_at.disabled, true);
  assert.equal(fields.title.disabled, false);
  assert.equal(fields.capacity.disabled, false);

  let capturedMethod = null;
  let capturedBody = null;
  global.FormData = class {
    get(key) {
      return fields[key]?.value ?? "";
    }
  };
  global.fetch = async (url, options = {}) => {
    if (url === "/api/v1/events/12") {
      capturedMethod = options.method;
      capturedBody = JSON.parse(options.body);
      return response(409, { message: "Event capacity cannot be reduced below active registrations" });
    }
    return response(200, {});
  };

  await auth.createClubEvent({ preventDefault() {}, currentTarget: form });
  assert.equal(capturedMethod, "PATCH");
  assert.equal("visibility" in capturedBody, false);
  assert.equal("starts_at" in capturedBody, false);
  assert.equal(
    nodes.get("#manager-events-message").textContent,
    "Event capacity cannot be reduced below active registrations",
  );
});

test("manager task board renders progress, members, and escapes task content", async () => {
  const nodes = installDom();
  global.document.createElement = () => ({
    _text: "",
    set textContent(value) {
      this._text = String(value);
    },
    get innerHTML() {
      return this._text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    },
  });
  auth.replaceSession("valid-token");
  global.fetch = async (url) => {
    if (url === "/api/v1/events/5/task-progress") {
      return response(200, {
        event_id: 5,
        total: 2,
        todo: 1,
        in_progress: 0,
        done: 1,
        completion_percentage: 50.0,
      });
    }
    if (url.startsWith("/api/v1/events/5/tasks?")) {
      return response(200, {
        items: [
          {
            id: 10,
            title: "<img src=x onerror=alert(1)>",
            description: "Stage setup",
            status: "TODO",
            assignee_membership_id: 202,
            assignee_name: "Bao Tran",
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      });
    }
    if (url.startsWith("/api/v1/clubs/11/members?")) {
      return response(200, {
        items: [{ membership_id: 202, user_id: 4, full_name: "Bao Tran", role: "MEMBER" }],
        total: 1,
        page: 1,
        page_size: 100,
      });
    }
    return response(200, {});
  };

  await auth.loadManagerTaskBoard(5, 11, auth.state.generation);
  assert.ok(nodes.get("#manager-task-progress").textContent.includes("50%"));
  assert.ok(nodes.get("#task-assignee-select").innerHTML.includes('value="202"'));
  const tasksHtml = nodes.get("#manager-tasks-list").innerHTML;
  assert.ok(!tasksHtml.includes("<img src=x onerror=alert(1)>"));
  assert.ok(tasksHtml.includes("&lt;img src=x onerror=alert(1)&gt;"));
});

test("member my-tasks handles status update error without mock fallback", async () => {
  const nodes = installDom();
  auth.replaceSession("valid-token");
  global.document.querySelector = (selector) => {
    if (selector === 'select[data-my-task-select="10"]') return { value: "DONE" };
    return nodes.get(selector);
  };
  global.fetch = async (url, options = {}) => {
    if (url === "/api/v1/event-tasks/10/status" && options.method === "PATCH") {
      return response(403, { message: "You do not have permission to access or update this task" });
    }
    return response(200, { items: [], total: 0, page: 1, page_size: 20 });
  };

  const button = { dataset: { myTaskSave: "10" }, disabled: false };
  await auth.handleMyTaskAction({ target: { closest: () => button } });
  assert.equal(button.disabled, false);
  assert.equal(
    nodes.get("#my-tasks-message").textContent,
    "You do not have permission to access or update this task",
  );
});
