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
const eventsUiState = {
  eventsPage: 1,
  myRegsPage: 1,
  mgrEventsPage: 1,
  participantsEventId: null,
  participantsPage: 1,
  editingEvent: null,
  managedEventsById: new Map(),
};
function resetEventsUiState() {
  eventsUiState.eventsPage = 1;
  eventsUiState.myRegsPage = 1;
  eventsUiState.mgrEventsPage = 1;
  eventsUiState.participantsEventId = null;
  eventsUiState.participantsPage = 1;
  eventsUiState.editingEvent = null;
  eventsUiState.managedEventsById.clear();
}
function replaceSession(accessToken) {
  state.generation += 1;
  state.accessToken = accessToken;
  state.user = null;
  resetEventsUiState();
}
function invalidateSession() {
  state.generation += 1;
  state.accessToken = null;
  state.user = null;
  resetEventsUiState();
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
  await loadEventsWorkspace(memberships, generation);
}

function eventCard(event) {
  const isRegistered = Boolean(event.is_registered);
  const isFull = event.registration_count >= event.capacity;
  const actionButton = isRegistered
    ? `<button type="button" class="secondary" data-event-cancel-reg="${event.id}">Cancel registration</button>`
    : `<button type="button" class="primary-action" data-event-register="${event.id}" ${isFull ? "disabled" : ""}>${isFull ? "Full" : "Register"}</button>`;
  return `<article class="card">
    <h3>${escapeHtml(event.title)}</h3>
    <p class="meta">${escapeHtml(event.club_name)} • ${escapeHtml(event.visibility)} • ${event.registration_count}/${event.capacity}</p>
    <p>${escapeHtml(event.location)} • ${escapeHtml(new Date(event.starts_at).toLocaleString())}</p>
    <div class="actions">
      <button type="button" class="secondary" data-event-detail="${event.id}">Details</button>
      ${actionButton}
    </div>
  </article>`;
}

function registrationCard(reg) {
  const canCancel = reg.status === "REGISTERED" && reg.event_status === "PUBLISHED";
  return `<article class="card">
    <h3>${escapeHtml(reg.event_title)}</h3>
    <p class="meta">${escapeHtml(reg.club_name)} • ${escapeHtml(reg.status)} • Event: ${escapeHtml(reg.event_status)}</p>
    <p>Starts: ${escapeHtml(new Date(reg.event_starts_at).toLocaleString())}</p>
    ${canCancel ? `<div class="actions"><button type="button" class="secondary" data-event-cancel-reg="${reg.event_id}">Cancel registration</button></div>` : ""}
  </article>`;
}

function managerEventCard(event) {
  const editBtn =
    event.status === "DRAFT" || event.status === "PUBLISHED"
      ? `<button type="button" class="secondary" data-mgr-event-edit="${event.id}">Edit</button>`
      : "";
  const publishBtn =
    event.status === "DRAFT"
      ? `<button type="button" class="primary-action" data-mgr-event-publish="${event.id}">Publish</button>`
      : "";
  const cancelBtn =
    event.status === "DRAFT" || event.status === "PUBLISHED"
      ? `<button type="button" class="secondary" data-mgr-event-cancel="${event.id}">Cancel event</button>`
      : "";
  return `<article class="card">
    <h3>${escapeHtml(event.title)}</h3>
    <p class="meta">${escapeHtml(event.club_name)} • ${escapeHtml(event.status)} • ${event.registration_count}/${event.capacity}</p>
    <p>${escapeHtml(event.location)} • ${escapeHtml(new Date(event.starts_at).toLocaleString())}</p>
    <div class="actions">
      ${editBtn}
      ${publishBtn}
      ${cancelBtn}
      <button type="button" class="secondary" data-mgr-event-participants="${event.id}">Participants</button>
    </div>
  </article>`;
}

function renderPagination(node, page, pageSize, total, scope) {
  if (!node) return;
  const totalPages = Math.max(1, Math.ceil((total || 0) / pageSize));
  node.innerHTML = `
    <button type="button" class="secondary" data-page-scope="${scope}" data-page-dir="prev" ${page <= 1 ? "disabled" : ""}>Previous</button>
    <span class="meta">Page ${page} of ${totalPages}</span>
    <button type="button" class="secondary" data-page-scope="${scope}" data-page-dir="next" ${page >= totalPages ? "disabled" : ""}>Next</button>
  `;
}

function toDatetimeLocalValue(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function setEventFormMode(eventItem) {
  const form = $("#event-create-form");
  const submitBtn = $("#event-submit-btn");
  const cancelEditBtn = $("#event-edit-cancel");
  eventsUiState.editingEvent = eventItem
    ? { id: eventItem.id, status: eventItem.status, club_id: eventItem.club_id }
    : null;
  if (!form) return;

  const setField = (name, value, disabled = false) => {
    const field = form.elements?.[name] || form.querySelector?.(`[name="${name}"]`);
    if (!field) return;
    if (value !== undefined) field.value = value;
    field.disabled = disabled;
  };

  if (!eventItem) {
    form.reset?.();
    setField("club_id", undefined, false);
    setField("visibility", "PUBLIC_STUDENTS", false);
    setField("starts_at", "", false);
    setField("ends_at", "", false);
    setField("registration_opens_at", "", false);
    if (submitBtn) submitBtn.textContent = "Create draft event";
    cancelEditBtn?.classList.add("hidden");
    return;
  }

  const isPublished = eventItem.status === "PUBLISHED";
  setField("club_id", String(eventItem.club_id), true);
  setField("title", eventItem.title || "", false);
  setField("location", eventItem.location || "", false);
  setField("description", eventItem.description || "", false);
  setField("visibility", eventItem.visibility || "PUBLIC_STUDENTS", isPublished);
  setField("capacity", String(eventItem.capacity ?? 1), false);
  setField("starts_at", toDatetimeLocalValue(eventItem.starts_at), isPublished);
  setField("ends_at", toDatetimeLocalValue(eventItem.ends_at), isPublished);
  setField(
    "registration_opens_at",
    toDatetimeLocalValue(eventItem.registration_opens_at),
    isPublished,
  );
  setField(
    "registration_closes_at",
    toDatetimeLocalValue(eventItem.registration_closes_at),
    false,
  );
  setField(
    "cancellation_deadline_at",
    toDatetimeLocalValue(eventItem.cancellation_deadline_at),
    false,
  );
  if (submitBtn) submitBtn.textContent = "Save event changes";
  cancelEditBtn?.classList.remove("hidden");
}

async function loadEventsWorkspace(memberships, generation = state.generation) {
  const eventsNode = $("#events-list");
  const myRegsNode = $("#my-registrations-list");
  if (!eventsNode || !myRegsNode) return;

  const pageSize = 20;
  const [eventsPage, myRegsPage] = await Promise.all([
    api(`/api/v1/events?page=${eventsUiState.eventsPage}&page_size=${pageSize}`),
    api(`/api/v1/event-registrations/mine?page=${eventsUiState.myRegsPage}&page_size=${pageSize}`),
  ]);
  if (state.generation !== generation) return;

  eventsNode.className = "cards discovery-grid";
  eventsNode.innerHTML =
    eventsPage.items && eventsPage.items.length
      ? eventsPage.items.map((item) => eventCard(item)).join("")
      : '<p class="empty">No published events available.</p>';
  renderPagination(
    $("#events-pagination"),
    eventsPage.page || eventsUiState.eventsPage,
    eventsPage.page_size || pageSize,
    eventsPage.total || 0,
    "events",
  );

  myRegsNode.className = "cards";
  myRegsNode.innerHTML =
    myRegsPage.items && myRegsPage.items.length
      ? myRegsPage.items.map((item) => registrationCard(item)).join("")
      : '<p class="empty">No event registrations yet.</p>';
  renderPagination(
    $("#my-registrations-pagination"),
    myRegsPage.page || eventsUiState.myRegsPage,
    myRegsPage.page_size || pageSize,
    myRegsPage.total || 0,
    "my-registrations",
  );

  const mgrPanel = $("#manager-events-panel");
  const mgrList = $("#manager-events-list");
  const clubSelect = $("#event-club-select");
  if (!mgrPanel || !mgrList || !clubSelect) return;

  const managed = memberships.filter((m) => m.status === "ACTIVE" && m.role === "MANAGER");
  if (!managed.length) {
    mgrPanel.classList.add("hidden");
    mgrList.innerHTML = "";
    eventsUiState.managedEventsById.clear();
    return;
  }

  const prevClubId = clubSelect.value;
  clubSelect.innerHTML = managed
    .map((m) => `<option value="${m.club.id}">${escapeHtml(m.club.name)}</option>`)
    .join("");
  if (prevClubId && managed.some((m) => String(m.club.id) === prevClubId)) {
    clubSelect.value = prevClubId;
  }
  const activeClubId = Number(clubSelect.value || managed[0].club.id);
  const clubEventsPage = await api(
    `/api/v1/clubs/${activeClubId}/events?page=${eventsUiState.mgrEventsPage}&page_size=${pageSize}`,
  );
  if (state.generation !== generation) return;

  const items = clubEventsPage.items || [];
  eventsUiState.managedEventsById.clear();
  items.forEach((item) => eventsUiState.managedEventsById.set(item.id, item));
  mgrPanel.classList.remove("hidden");
  mgrList.className = "cards";
  mgrList.innerHTML = items.length
    ? items.map((item) => managerEventCard(item)).join("")
    : '<p class="empty">No events created for this club yet.</p>';
  renderPagination(
    $("#manager-events-pagination"),
    clubEventsPage.page || eventsUiState.mgrEventsPage,
    clubEventsPage.page_size || pageSize,
    clubEventsPage.total || 0,
    "manager-events",
  );
}

async function handleEventAction(event) {
  const detailBtn = event.target.closest("button[data-event-detail]");
  const registerBtn = event.target.closest("button[data-event-register]");
  const cancelBtn = event.target.closest("button[data-event-cancel-reg]");
  if (!detailBtn && !registerBtn && !cancelBtn) return;

  const generation = state.generation;
  const msgNode = $("#events-message");
  if (detailBtn) {
    const detailNode = $("#event-detail-panel");
    try {
      const item = await api(`/api/v1/events/${detailBtn.dataset.eventDetail}`);
      if (state.generation !== generation || !detailNode) return;
      detailNode.classList.remove("hidden");
      detailNode.innerHTML = `<h3>${escapeHtml(item.title)}</h3>
        <p class="meta">${escapeHtml(item.club_name)} • ${escapeHtml(item.visibility)} • ${item.registration_count}/${item.capacity}</p>
        <p>${escapeHtml(item.description)}</p>
        <p>Location: ${escapeHtml(item.location)}</p>`;
    } catch (error) {
      if (state.generation === generation && msgNode) message(msgNode, error.message, "error");
    }
    return;
  }

  const button = registerBtn || cancelBtn;
  button.disabled = true;
  if (msgNode) message(msgNode, registerBtn ? "Registering…" : "Cancelling registration…");
  try {
    if (registerBtn) {
      await api(`/api/v1/events/${registerBtn.dataset.eventRegister}/registrations`, {
        method: "POST",
      });
    } else {
      await api(`/api/v1/events/${cancelBtn.dataset.eventCancelReg}/registrations/me`, {
        method: "DELETE",
      });
    }
    if (state.generation !== generation) return;
    if (msgNode) {
      message(
        msgNode,
        registerBtn ? "Registered for event." : "Registration cancelled.",
        "success",
      );
    }
    await loadStudent(generation);
  } catch (error) {
    if (state.generation !== generation) return;
    button.disabled = false;
    if (msgNode) message(msgNode, error.message, "error");
  }
}

async function createClubEvent(event) {
  event.preventDefault();
  const generation = state.generation;
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const clubId = form.get("club_id");
  const msgNode = $("#manager-events-message");
  const editing = eventsUiState.editingEvent;
  if (msgNode) message(msgNode, editing ? "Saving event changes…" : "Creating draft event…");
  const toIso = (raw) => new Date(String(raw)).toISOString();
  const rawCancel = String(form.get("cancellation_deadline_at") || "").trim();

  let payload;
  if (editing && editing.status === "PUBLISHED") {
    payload = {
      title: String(form.get("title") || ""),
      description: String(form.get("description") || ""),
      location: String(form.get("location") || ""),
      capacity: Number(form.get("capacity")),
      registration_closes_at: toIso(form.get("registration_closes_at")),
      cancellation_deadline_at: rawCancel ? toIso(rawCancel) : null,
    };
  } else {
    payload = {
      title: String(form.get("title") || ""),
      description: String(form.get("description") || ""),
      location: String(form.get("location") || ""),
      visibility: String(form.get("visibility") || "PUBLIC_STUDENTS"),
      capacity: Number(form.get("capacity")),
      starts_at: toIso(form.get("starts_at")),
      ends_at: toIso(form.get("ends_at")),
      registration_opens_at: toIso(form.get("registration_opens_at")),
      registration_closes_at: toIso(form.get("registration_closes_at")),
      cancellation_deadline_at: rawCancel ? toIso(rawCancel) : null,
    };
  }

  try {
    if (editing) {
      await api(`/api/v1/events/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    } else {
      await api(`/api/v1/clubs/${clubId}/events`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    if (state.generation !== generation) return;
    setEventFormMode(null);
    if (msgNode) message(msgNode, editing ? "Event updated." : "Draft event created.", "success");
    await loadStudent(generation);
  } catch (error) {
    if (state.generation !== generation) return;
    if (msgNode) message(msgNode, error.message, "error");
  }
}

async function loadEventParticipants(eventId, generation = state.generation) {
  const listNode = $("#manager-participants-list");
  const pageNode = $("#manager-participants-pagination");
  const msgNode = $("#manager-events-message");
  const pageSize = 20;
  try {
    const data = await api(
      `/api/v1/events/${eventId}/registrations?page=${eventsUiState.participantsPage}&page_size=${pageSize}`,
    );
    if (state.generation !== generation || !listNode) return;
    eventsUiState.participantsEventId = eventId;
    listNode.classList.remove("hidden");
    listNode.innerHTML = data.items.length
      ? data.items
          .map(
            (p) =>
              `<article class="card"><strong>${escapeHtml(p.full_name)}</strong><p class="meta">${escapeHtml(p.status)}</p></article>`,
          )
          .join("")
      : '<p class="empty">No participants yet.</p>';
    pageNode?.classList.remove("hidden");
    renderPagination(
      pageNode,
      data.page || eventsUiState.participantsPage,
      data.page_size || pageSize,
      data.total || 0,
      "participants",
    );
  } catch (error) {
    if (state.generation === generation && msgNode) message(msgNode, error.message, "error");
  }
}

async function handleManagerEventAction(event) {
  const editBtn = event.target.closest("button[data-mgr-event-edit]");
  const publishBtn = event.target.closest("button[data-mgr-event-publish]");
  const cancelBtn = event.target.closest("button[data-mgr-event-cancel]");
  const participantsBtn = event.target.closest("button[data-mgr-event-participants]");
  if (!editBtn && !publishBtn && !cancelBtn && !participantsBtn) return;

  const generation = state.generation;
  const msgNode = $("#manager-events-message");
  if (editBtn) {
    const eventItem = eventsUiState.managedEventsById.get(Number(editBtn.dataset.mgrEventEdit));
    if (eventItem) {
      setEventFormMode(eventItem);
      if (msgNode) message(msgNode, `Editing "${eventItem.title}" (${eventItem.status}).`);
    }
    return;
  }
  if (participantsBtn) {
    eventsUiState.participantsPage = 1;
    await loadEventParticipants(Number(participantsBtn.dataset.mgrEventParticipants), generation);
    return;
  }

  const button = publishBtn || cancelBtn;
  button.disabled = true;
  try {
    if (publishBtn) {
      await api(`/api/v1/events/${publishBtn.dataset.mgrEventPublish}/publish`, {
        method: "POST",
      });
    } else {
      const reason = window.prompt("Reason for cancelling event:");
      if (reason === null) {
        button.disabled = false;
        return;
      }
      await api(`/api/v1/events/${cancelBtn.dataset.mgrEventCancel}/cancel`, {
        method: "POST",
        body: JSON.stringify({ cancellation_reason: reason }),
      });
    }
    if (state.generation !== generation) return;
    if (msgNode) {
      message(msgNode, publishBtn ? "Event published." : "Event cancelled.", "success");
    }
    await loadStudent(generation);
  } catch (error) {
    if (state.generation !== generation) return;
    button.disabled = false;
    if (msgNode) message(msgNode, error.message, "error");
  }
}

async function handlePaginationClick(event) {
  const button = event.target.closest("button[data-page-scope]");
  if (!button || button.disabled) return;
  const delta = button.dataset.pageDir === "next" ? 1 : -1;
  const scope = button.dataset.pageScope;
  if (scope === "events") eventsUiState.eventsPage = Math.max(1, eventsUiState.eventsPage + delta);
  else if (scope === "my-registrations")
    eventsUiState.myRegsPage = Math.max(1, eventsUiState.myRegsPage + delta);
  else if (scope === "manager-events")
    eventsUiState.mgrEventsPage = Math.max(1, eventsUiState.mgrEventsPage + delta);
  else if (scope === "participants" && eventsUiState.participantsEventId !== null) {
    eventsUiState.participantsPage = Math.max(1, eventsUiState.participantsPage + delta);
    await loadEventParticipants(eventsUiState.participantsEventId, state.generation);
    return;
  }
  await loadStudent(state.generation);
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
  $("#events-list")?.addEventListener("click", handleEventAction);
  $("#my-registrations-list")?.addEventListener("click", handleEventAction);
  $("#event-create-form")?.addEventListener("submit", createClubEvent);
  $("#event-edit-cancel")?.addEventListener("click", () => setEventFormMode(null));
  $("#event-club-select")?.addEventListener("change", () => {
    eventsUiState.mgrEventsPage = 1;
    loadStudent(state.generation);
  });
  $("#manager-events-list")?.addEventListener("click", handleManagerEventAction);
  $("#events-pagination")?.addEventListener("click", handlePaginationClick);
  $("#my-registrations-pagination")?.addEventListener("click", handlePaginationClick);
  $("#manager-events-pagination")?.addEventListener("click", handlePaginationClick);
  $("#manager-participants-pagination")?.addEventListener("click", handlePaginationClick);
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
    loadEventsWorkspace,
    handleEventAction,
    createClubEvent,
    handleManagerEventAction,
    handlePaginationClick,
    setEventFormMode,
    eventsUiState,
  };
