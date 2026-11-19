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
    const payload = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
    const error = new Error(payload.message || `HTTP ${response.status}`);
    error.status = response.status;
    error.errorCode = payload.error_code;
    throw error;
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

function membershipApplicationCard(application, manager = false) {
  const reason = application.rejection_reason
    ? `<p class="reason">${escapeHtml(application.rejection_reason)}</p>`
    : "";
  const applicant = manager
    ? `<p><strong>${escapeHtml(application.applicant.full_name)}</strong></p>`
    : "";
  const motivation = application.motivation
    ? `<p>${escapeHtml(application.motivation)}</p>`
    : '<p class="meta">No motivation provided.</p>';
  const actions = manager
    ? `<div class="actions"><button data-membership-action="approve" data-id="${application.id}">Approve</button><button class="danger" data-membership-action="reject" data-id="${application.id}">Reject</button></div>`
    : "";
  return `<article class="card">${applicant}<div class="card-heading"><h3>${escapeHtml(application.club.name)}</h3><span class="badge ${application.status.toLowerCase()}">${application.status}</span></div>${motivation}${reason}${actions}</article>`;
}

function renderDiscovery(clubs, applications, memberships) {
  const activeClubIds = new Set(
    memberships.filter((item) => item.status === "ACTIVE").map((item) => item.club.id),
  );
  const pendingClubIds = new Set(
    applications.filter((item) => item.status === "PENDING").map((item) => item.club.id),
  );
  const removedClubIds = new Set(
    memberships.filter((item) => item.status === "REMOVED").map((item) => item.club.id),
  );
  $("#discovery-list").className = "cards discovery-grid";
  $("#discovery-list").innerHTML = clubs.length
    ? clubs
        .map((club) => {
          let action;
          if (activeClubIds.has(club.id)) {
            action = '<p class="success"><strong>Active member</strong></p>';
          } else if (pendingClubIds.has(club.id)) {
            action = '<p class="pending badge">Application pending</p>';
          } else if (removedClubIds.has(club.id)) {
            action = '<p class="reason">Reapplication after removal is unavailable in V1.</p>';
          } else {
            action = `<form class="join-form" data-club-id="${club.id}"><label>Why do you want to join?<textarea name="motivation" maxlength="2000" placeholder="Optional motivation"></textarea></label><button>Send join request</button></form>`;
          }
          return `<article class="card"><h3>${escapeHtml(club.name)}</h3><p class="meta">${escapeHtml(club.category)}</p><p>${escapeHtml(club.description)}</p>${action}</article>`;
        })
        .join("")
    : '<p class="empty">No active clubs are available.</p>';
}

function renderMembershipApplications(applications) {
  $("#membership-application-list").className = "cards membership-grid";
  $("#membership-application-list").innerHTML = applications.length
    ? applications.map((item) => membershipApplicationCard(item)).join("")
    : '<p class="empty">No membership applications yet.</p>';
}

function renderMemberships(memberships) {
  $("#membership-list").className = "cards membership-grid";
  $("#membership-list").innerHTML = memberships.length
    ? memberships
        .map((membership) => {
          const leaveAction =
            membership.status === "ACTIVE" && membership.role === "MEMBER"
              ? `<button class="danger" data-leave-membership="${membership.id}">Leave club</button>`
              : "";
          return `<article class="card"><div class="card-heading"><h3>${escapeHtml(membership.club.name)}</h3><span class="badge ${membership.status === "ACTIVE" ? "approved" : "rejected"}">${membership.status}</span></div><p class="meta">${membership.role}</p>${leaveAction}</article>`;
        })
        .join("")
    : '<p class="empty">You have no membership history.</p>';
}

async function loadManagerQueues(memberships, generation) {
  const managed = memberships.filter(
    (membership) => membership.status === "ACTIVE" && membership.role === "MANAGER",
  );
  if (!managed.length) {
    $("#manager-panel").classList.add("hidden");
    return;
  }
  const queues = await Promise.all(
    managed.map(async (membership) => ({
      membership,
      applications: await api(
        `/api/v1/clubs/${membership.club.id}/membership-applications/pending`,
      ),
    })),
  );
  if (state.generation !== generation) return;
  $("#manager-panel").classList.remove("hidden");
  $("#manager-membership-list").className = "cards";
  $("#manager-membership-list").innerHTML = queues
    .map(({ membership, applications }) => {
      const cards = applications.length
        ? applications.map((item) => membershipApplicationCard(item, true)).join("")
        : '<p class="empty">No pending applications.</p>';
      return `<section class="manager-club-group"><h3>${escapeHtml(membership.club.name)}</h3>${cards}</section>`;
    })
    .join("");
}

async function loadStudent(generation = state.generation) {
  const [requests, clubs, activeClubs, applications, memberships] = await Promise.all([
    api("/api/v1/club-requests/mine"),
    api("/api/v1/clubs/mine"),
    api("/api/v1/clubs"),
    api("/api/v1/membership-applications/mine"),
    api("/api/v1/memberships/mine"),
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
  renderDiscovery(activeClubs, applications, memberships);
  renderMembershipApplications(applications);
  renderMemberships(memberships);
  await loadManagerQueues(memberships, generation);
}

async function submitMembershipApplication(event) {
  const formElement = event.target.closest("form[data-club-id]");
  if (!formElement) return;
  event.preventDefault();
  const generation = state.generation;
  const button = formElement.querySelector("button");
  const form = new FormData(formElement);
  button.disabled = true;
  message($("#student-message"), "Submitting membership application…");
  try {
    const motivation = String(form.get("motivation") || "").trim();
    await api(`/api/v1/clubs/${formElement.dataset.clubId}/membership-applications`, {
      method: "POST",
      body: JSON.stringify({ motivation: motivation || null }),
    });
    if (state.generation !== generation) return;
    message($("#student-message"), "Membership application submitted.", "success");
    await loadStudent(generation);
  } catch (error) {
    if (state.generation !== generation) return;
    button.disabled = false;
    message($("#student-message"), error.message, "error");
  }
}

async function leaveClub(event) {
  const button = event.target.closest("button[data-leave-membership]");
  if (!button) return;
  if (!window.confirm("Leave this club? Your membership history will be preserved.")) return;
  const generation = state.generation;
  button.disabled = true;
  message($("#student-message"), "Leaving club…");
  try {
    await api(`/api/v1/memberships/${button.dataset.leaveMembership}/leave`, {
      method: "POST",
    });
    if (state.generation !== generation) return;
    message($("#student-message"), "You have left the club.", "success");
    await loadStudent(generation);
  } catch (error) {
    if (state.generation !== generation) return;
    button.disabled = false;
    message($("#student-message"), error.message, "error");
  }
}

async function reviewMembershipApplication(event) {
  const button = event.target.closest("button[data-membership-action]");
  if (!button) return;
  const generation = state.generation;
  button.disabled = true;
  message($("#manager-message"), "Saving decision…");
  try {
    const options = { method: "POST" };
    if (button.dataset.membershipAction === "reject") {
      const reason = window.prompt("Reason for rejection:");
      if (reason === null) {
        button.disabled = false;
        message($("#manager-message"), "");
        return;
      }
      options.body = JSON.stringify({ rejection_reason: reason });
    }
    await api(
      `/api/v1/membership-applications/${button.dataset.id}/${button.dataset.membershipAction}`,
      options,
    );
    if (state.generation !== generation) return;
    message($("#manager-message"), "Membership decision saved.", "success");
    await loadStudent(generation);
  } catch (error) {
    if (state.generation !== generation) return;
    if (error.status !== 409) button.disabled = false;
    message(
      $("#manager-message"),
      error.status === 409
        ? "This application was already processed. Reloaded current state."
        : error.message,
      error.status === 409 ? "" : "error",
    );
    if (error.status === 409) await loadStudent(generation);
  }
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
  $("#discovery-list").addEventListener("submit", submitMembershipApplication);
  $("#membership-list").addEventListener("click", leaveClub);
  $("#manager-membership-list").addEventListener("click", reviewMembershipApplication);
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
    submitMembershipApplication,
    leaveClub,
    reviewMembershipApplication,
  };
