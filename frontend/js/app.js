const state = { accessToken: null, user: null, generation: 0 };
let refreshPromise = null;
let refreshGeneration = null;
const $ = (selector) => document.querySelector(selector);
function show(view) {
  ["#login-view", "#student-view", "#admin-view"].forEach((id) => $(id).classList.add("hidden"));
  $(view).classList.remove("hidden");
}
function message(target, text, kind = "") {
  target.textContent = text;
  target.className = `message ${kind}`;
}
function setPasswordVisibility(visible) {
  const input = $("#login-password");
  const toggle = $("#password-toggle");
  input.type = visible ? "text" : "password";
  toggle.setAttribute("aria-pressed", String(visible));
  toggle.setAttribute("aria-label", visible ? "Hide password" : "Show password");
  $("[data-password-icon='eye']").classList.toggle("hidden", visible);
  $("[data-password-icon='eye-off']").classList.toggle("hidden", !visible);
  input.focus({ preventScroll: true });
}
function replaceSession(accessToken) {
  state.generation += 1;
  state.accessToken = accessToken;
  state.user = null;
}
function invalidateSession() {
  state.generation += 1;
  state.accessToken = null;
  state.user = null;
}
function refreshAccessToken() {
  if (refreshPromise && refreshGeneration === state.generation) return refreshPromise;
  const generation = state.generation;
  const pending = (async () => {
    try {
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { Origin: location.origin },
      });
      if (!response.ok) return false;
      const result = await response.json();
      if (state.generation !== generation) return false;
      state.accessToken = result.access_token;
      return true;
    } catch (_error) {
      return false;
    }
  })();
  refreshPromise = pending;
  refreshGeneration = generation;
  pending.finally(() => {
    if (refreshPromise === pending) {
      refreshPromise = null;
      refreshGeneration = null;
    }
  });
  return pending;
}
async function api(path, options = {}, retry = true) {
  const generation = state.generation;
  const accessToken = state.accessToken;
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && retry && state.generation === generation) {
    if (state.accessToken && state.accessToken !== accessToken) return api(path, options, false);
    if (await refreshAccessToken()) return api(path, options, false);
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
    throw new Error(error.message || `HTTP ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}
function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value;
  return node.innerHTML;
}
function requestCard(request, admin = false) {
  const reason = request.rejection_reason
    ? `<p class="reason">${escapeHtml(request.rejection_reason)}</p>`
    : "";
  const actions = admin
    ? `<div class="actions"><button data-action="approve" data-id="${request.id}">Approve</button><button class="danger" data-action="reject" data-id="${request.id}">Reject</button></div>`
    : "";
  return `<article class="card"><div class="card-heading"><h3>${escapeHtml(request.proposed_name)}</h3><span class="badge ${request.status.toLowerCase()}">${request.status}</span></div><p class="meta">${escapeHtml(request.category)}</p><p>${escapeHtml(request.mission)}</p><details><summary>Initial plan</summary><p>${escapeHtml(request.initial_plan)}</p></details>${reason}${actions}</article>`;
}
async function loadStudent(generation = state.generation) {
  const [requests, clubs] = await Promise.all([
    api("/api/v1/club-requests/mine"),
    api("/api/v1/clubs/mine"),
  ]);

  if (state.generation !== generation) {
    return;
  }

  $("#request-list").className = "cards";
  $("#request-list").innerHTML = requests.length
    ? requests.map((item) => requestCard(item)).join("")
    : '<p class="empty">No requests yet.</p>';
  $("#club-list").className = "cards";
  $("#club-list").innerHTML = clubs.length
    ? clubs
        .map(
          (club) =>
            `<article class="card"><h3>${escapeHtml(club.name)}</h3><p class="meta">${escapeHtml(club.category)}</p><p>${escapeHtml(club.description)}</p></article>`,
        )
        .join("")
    : '<p class="empty">Approved clubs will appear here.</p>';
}
async function loadAdmin(generation = state.generation) {
  const requests = await api("/api/v1/admin/club-requests/pending");

  if (state.generation !== generation) {
    return;
  }

  $("#admin-list").className = "cards";
  $("#admin-list").innerHTML = requests.length
    ? requests.map((item) => requestCard(item, true)).join("")
    : '<p class="empty">No pending requests.</p>';
}
function showSignedOut(messageText = "") {
  invalidateSession();
  $("#session-summary").textContent = "Signed out";
  show("#login-view");
  message($("#login-message"), messageText, messageText ? "success" : "");
}
async function loadSessionData(generation = state.generation) {
  const role = state.user.global_role;
  const target = role === "ADMIN" ? $("#admin-message") : $("#student-message");

  try {
    if (role === "ADMIN") {
      await loadAdmin(generation);
    } else {
      await loadStudent(generation);
    }

    if (state.generation !== generation) {
      return;
    }

    message(target, "");
  } catch (error) {
    if (state.generation !== generation) {
      return;
    }

    message(target, `Unable to load club data: ${error.message}`, "error");
  }
}
async function establishSession() {
  const generation = state.generation;
  try {
    if (!state.accessToken && !(await refreshAccessToken())) throw new Error("No session");
    const user = await api("/api/v1/auth/me");
    if (state.generation !== generation) return;
    state.user = user;
  } catch (_error) {
    if (state.generation === generation) showSignedOut();
    return;
  }
  $("#session-summary").textContent = `${state.user.full_name} · ${state.user.global_role}`;
  show(state.user.global_role === "ADMIN" ? "#admin-view" : "#student-view");
  await loadSessionData(generation);
}
async function login(event) {
  event.preventDefault();
  message($("#login-message"), "Signing in…");
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  try {
    const result = await api(
      "/api/v1/auth/login",
      {
        method: "POST",
        headers: { Origin: location.origin },
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      },
      false,
    );
    replaceSession(result.access_token);
    formElement.reset();
    await establishSession();
  } catch (error) {
    message($("#login-message"), error.message, "error");
  }
}
async function submitClubRequest(event) {
  event.preventDefault();
  const generation = state.generation;
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  message($("#student-message"), "Submitting…");
  try {
    await api("/api/v1/club-requests", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(form)),
    });
    if (state.generation !== generation) {
      return;
    }

    formElement.reset();
    message($("#student-message"), "Request submitted successfully.", "success");
    await loadStudent(generation);
  } catch (error) {
    if (state.generation !== generation) {
      return;
    }

    message($("#student-message"), error.message, "error");
  }
}
async function reviewClubRequest(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const generation = state.generation;
  button.disabled = true;
  message($("#admin-message"), "Saving decision…");
  try {
    if (button.dataset.action === "approve")
      await api(`/api/v1/admin/club-requests/${button.dataset.id}/approve`, { method: "POST" });
    else {
      const reason = window.prompt("Reason for rejection:");
      if (reason === null) {
        button.disabled = false;
        message($("#admin-message"), "");
        return;
      }
      await api(`/api/v1/admin/club-requests/${button.dataset.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ rejection_reason: reason }),
      });
    }
    if (state.generation !== generation) {
      return;
    }

    message($("#admin-message"), "Decision saved.", "success");
    await loadAdmin(generation);
  } catch (error) {
    if (state.generation !== generation) {
      return;
    }

    button.disabled = false;
    message($("#admin-message"), error.message, "error");
  }
}
async function logout() {
  const target = state.user?.global_role === "ADMIN" ? $("#admin-message") : $("#student-message");
  message(target, "Signing out…");
  try {
    const response = await fetch("/api/v1/auth/logout", {
      method: "POST",
      headers: { Origin: location.origin },
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
      throw new Error(error.message || `HTTP ${response.status}`);
    }
  } catch (error) {
    message(target, `Sign out failed: ${error.message}. Your session is still active.`, "error");
    return;
  }
  message($("#student-message"), "");
  message($("#admin-message"), "");
  showSignedOut("Signed out successfully.");
}
function initialize() {
  $("#login-form").addEventListener("submit", login);
  $("#club-request-form").addEventListener("submit", submitClubRequest);
  $("#admin-list").addEventListener("click", reviewClubRequest);
  $("#password-toggle").addEventListener("click", () =>
    setPasswordVisibility($("#login-password").type === "password"),
  );
  $("#logout-student").addEventListener("click", logout);
  $("#logout-admin").addEventListener("click", logout);
  establishSession();
}
if (typeof module === "undefined") initialize();
else
  module.exports = {
    api,
    invalidateSession,
    loadAdmin,
    loadSessionData,
    loadStudent,
    logout,
    reviewClubRequest,
    refreshAccessToken,
    replaceSession,
    setPasswordVisibility,
    state,
    submitClubRequest,
  };
