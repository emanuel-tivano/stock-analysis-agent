"use strict";

const SESSION_KEY = "stock-analysis-session-id";
const ACTION_KEY = "stock-analysis-action-id";
const form = document.querySelector("#composer");
const input = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const messages = document.querySelector("#messages");
const conversation = document.querySelector("#conversation");
const statusRegion = document.querySelector("#status");
const errorRegion = document.querySelector("#error");
const newConversationButton = document.querySelector("#new-conversation");

let sessionId = sessionStorage.getItem(SESSION_KEY);

class UserFacingError extends Error {}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function showError(message) {
  errorRegion.textContent = message;
  errorRegion.hidden = false;
}

function clearError() {
  errorRegion.textContent = "";
  errorRegion.hidden = true;
}

function setBusy(busy) {
  sendButton.disabled = busy;
  input.disabled = busy;
  statusRegion.textContent = busy ? "Analizando…" : "";
}

function setConversationEmpty(empty) {
  conversation.classList.toggle("is-empty", empty);
  conversation.dataset.state = empty ? "empty" : "active";
}

function scrollToLatest() {
  messages.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function addUserMessage(text) {
  setConversationEmpty(false);
  const article = element("article", "message message-user");
  article.append(element("span", "message-label", "Vos"), element("p", "", text));
  messages.append(article);
  scrollToLatest();
}

function addFact(container, label, value) {
  const wrapper = element("div", "fact");
  const list = element("dl");
  list.append(element("dt", "", label), element("dd", "", value));
  wrapper.append(list);
  container.append(wrapper);
}

function addDetailRow(list, label, value) {
  list.append(element("dt", "", label), element("dd", "", value));
}

function detailsPanel(label) {
  const details = element("details", "detail-panel");
  details.append(element("summary", "", label));
  const content = element("div", "detail-content");
  details.append(content);
  return { details, content };
}

function renderIndicators(article, data) {
  const panel = detailsPanel("Ver indicadores");
  const list = element("dl", "detail-list");
  for (const metric of data.indicators) {
    addDetailRow(list, metric.label, metric.display);
  }
  panel.content.append(list);
  article.append(panel.details);
}

function safeHttpUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

function renderSources(article, data) {
  const panel = detailsPanel("Ver fuentes");
  if (!data.sources.length) {
    panel.content.append(element("p", "", "No hay fuentes disponibles para esta evaluación."));
  } else {
    const list = element("ul");
    for (const source of data.sources) {
      const item = element("li");
      const href = safeHttpUrl(source.url);
      if (href) {
        const link = element("a", "source-link", source.url);
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        item.append(link);
      } else {
        item.append(element("span", "", "Fuente no disponible"));
      }
      const notes = [];
      if (source.data_date) notes.push(`datos al ${source.data_date}`);
      if (source.provisional) notes.push("provisional");
      if (notes.length) item.append(document.createTextNode(` — ${notes.join(", ")}`));
      list.append(item);
    }
    panel.content.append(list);
  }
  article.append(panel.details);
}

function renderTechnicalDetails(article, data) {
  if (!data.technical_details) return;
  const panel = detailsPanel("Ver detalles técnicos");
  const detail = data.technical_details;
  const list = element("dl", "detail-list");
  addDetailRow(list, "Tendencia", detail.trend.label);
  addDetailRow(list, "Momentum", detail.momentum.label);
  addDetailRow(list, "Estado del momentum", detail.momentum_state.label);
  addDetailRow(list, "Confirmación", detail.confirmation.label);
  addDetailRow(list, "Confianza", detail.confidence.label);
  addDetailRow(list, "Tamaño de muestra", detail.sample_size_display);
  addDetailRow(list, "ID de ejecución", detail.trace_id);
  panel.content.append(list);

  const missing = Object.entries(detail.missing_indicators);
  if (missing.length) {
    panel.content.append(element("h4", "", "Indicadores faltantes"));
    const missingList = element("ul");
    for (const [name, reason] of missing) {
      missingList.append(element("li", "", `${name}: ${reason}`));
    }
    panel.content.append(missingList);
  }

  if (detail.signal_explanations.length) {
    panel.content.append(element("h4", "", "Explicaciones de señales"));
    const explanations = element("dl", "detail-list");
    for (const explanation of detail.signal_explanations) {
      addDetailRow(explanations, explanation.label, explanation.text);
    }
    panel.content.append(explanations);
  }

  if (detail.warnings.length) {
    panel.content.append(element("h4", "", "Notas técnicas y de auditoría"));
    const technicalWarnings = element("ul");
    for (const warning of detail.warnings) {
      technicalWarnings.append(element("li", "", warning));
    }
    panel.content.append(technicalWarnings);
  }
  article.append(panel.details);
}

function renderAgentMessage(data) {
  if (data.status === "PAUSED" && data.pending_action) {
    renderAction(data.pending_action);
    return;
  }
  setConversationEmpty(false);
  const article = element("article", "message message-agent");
  article.append(element("span", "message-label", "Agente"));
  article.append(element("h3", "result-heading", data.heading));
  if (data.user_message) article.append(element("p", "", data.user_message));

  if (data.result_type === "successful_analysis") {
    const summary = element("div", "summary-grid");
    addFact(summary, "Sesgo técnico", data.conclusion.label);
    addFact(summary, "Confianza", data.confidence.label);
    article.append(summary);
    article.append(element("p", "", data.executive_summary));

    const metrics = element("div", "metrics-grid");
    addFact(metrics, "Tendencia", data.trend.label);
    addFact(metrics, "Momentum", data.momentum_state.short_label || data.momentum_state.label);
    addFact(metrics, "RSI", data.rsi.summary || data.rsi.display);
    addFact(metrics, "MACD", data.macd_summary);
    article.append(metrics);
  }

  const warnings = unique(data.warnings || []);
  if (warnings.length) {
    const warningBox = element("aside", "warning-box");
    warningBox.append(element("strong", "", "Advertencias"));
    const warningList = element("ul");
    for (const warning of warnings) warningList.append(element("li", "", warning));
    warningBox.append(warningList);
    article.append(warningBox);
  }

  if (!["asset_not_found", "ambiguous_asset"].includes(data.result_type)) {
    renderIndicators(article, data);
    renderSources(article, data);
    renderTechnicalDetails(article, data);
  }
  messages.append(article);
  scrollToLatest();
}

async function submitMessage(text) {
  if (sendButton.disabled) return;
  if (sessionStorage.getItem(ACTION_KEY)) {
    showError("Resolvé la revisión pendiente antes de iniciar otra consulta.");
    return;
  }
  const query = text.trim();
  clearError();
  if (!query) {
    showError("Escribí una consulta antes de enviarla.");
    input.focus();
    return;
  }

  addUserMessage(query);
  input.value = "";
  setBusy(true);
  try {
    const payload = { message: query };
    if (sessionId) payload.session_id = sessionId;
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new UserFacingError(
        "El servicio devolvió una respuesta inesperada. Intentá nuevamente.",
      );
    }
    if (!response.ok) {
      throw new UserFacingError(data.error?.message || "No pude procesar la consulta.");
    }
    sessionId = data.session_id;
    sessionStorage.setItem(SESSION_KEY, sessionId);
    renderAgentMessage(data);
  } catch (error) {
    showError(
      error instanceof UserFacingError
        ? error.message
        : "No pude conectarme con el servicio. Intentá nuevamente en unos minutos.",
    );
  } finally {
    setBusy(false);
    if (!sessionStorage.getItem(ACTION_KEY)) input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitMessage(input.value);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

for (const button of document.querySelectorAll(".example")) {
  button.addEventListener("click", () => {
    input.value = button.textContent.trim();
    input.focus();
  });
}

newConversationButton.addEventListener("click", () => {
  if (sessionStorage.getItem(ACTION_KEY)) {
    showError("Resolvé la revisión pendiente antes de iniciar otra conversación.");
    return;
  }
  sessionId = null;
  sessionStorage.removeItem(SESSION_KEY);
  messages.replaceChildren();
  const welcome = element("article", "welcome-card");
  welcome.append(
    element("h3", "", "Nueva conversación"),
    element("p", "", "Escribí una consulta para comenzar una sesión nueva."),
  );
  messages.append(welcome);
  setConversationEmpty(true);
  clearError();
  statusRegion.textContent = "";
  input.value = "";
  input.focus();
});

const SECTION_LABELS = {
  overview: "Resumen", trend: "Tendencia", momentum: "Momentum", risk: "Riesgos y limitaciones",
};

function clearActiveAction(actionId) {
  if (sessionStorage.getItem(ACTION_KEY) === actionId) sessionStorage.removeItem(ACTION_KEY);
}

function renderPublishedReport(result) {
  const article = element("article", "message message-agent");
  const title = element("h3", "result-heading", `Informe finalizado · ${result.ticker}`);
  title.tabIndex = -1;
  article.append(title, element("p", "", `Evidencia al ${result.as_of}. Aprobado sin recalcular datos.`));
  for (const [section, text] of Object.entries(result.publication.sections)) {
    article.append(element("h4", "", SECTION_LABELS[section]), element("p", "", text));
  }
  const note = result.publication.editorial.review_note;
  if (note) article.append(element("h4", "", "Comentario editorial humano"), element("p", "", note));
  article.append(element("p", "help-text", `Traza: ${result.trace_id}`));
  messages.append(article);
  title.focus();
  scrollToLatest();
}

function renderAction(action) {
  setConversationEmpty(false);
  const old = document.getElementById(`action-${action.action_id}`);
  if (old) old.remove();
  const article = element("article", "message message-agent review-card");
  article.id = `action-${action.action_id}`;
  const title = element("h3", "result-heading", `Revisar informe técnico · ${action.ticker}`);
  title.tabIndex = -1;
  article.append(title, element("p", "", action.summary));
  article.append(element("p", "help-text", `Datos al ${action.as_of} · Versión ${action.version} · ${action.status}`));
  const live = element("p", "status", "Todavía no se finalizó el informe. Aprobar utiliza únicamente la evidencia guardada.");
  live.setAttribute("aria-live", "polite");
  article.append(live);
  const terminal = !action.available_actions.length;
  if (terminal) {
    live.textContent = action.status === "REJECTED" ? "Informe rechazado; auditoría conservada." : "Informe finalizado.";
    clearActiveAction(action.action_id);
    messages.append(article);
    title.focus();
    return;
  }
  sessionId = action.session_id;
  sessionStorage.setItem(SESSION_KEY, sessionId);
  sessionStorage.setItem(ACTION_KEY, action.action_id);

  const editor = element("fieldset", "review-editor");
  editor.append(element("legend", "", "Presentación del informe"));
  const focusLabel = element("label", "", "Enfoque");
  const focus = element("select");
  for (const [key, label] of Object.entries(SECTION_LABELS)) {
    const option = element("option", "", label);
    option.value = key;
    focus.append(option);
  }
  focus.value = action.proposed_payload.focus;
  focusLabel.append(focus);
  editor.append(focusLabel);
  const sections = element("fieldset");
  sections.append(element("legend", "", "Secciones (riesgos siempre visibles)"));
  const checkboxes = [];
  for (const [key, label] of Object.entries(SECTION_LABELS)) {
    const wrapper = element("label", "review-check", label);
    const check = element("input");
    check.type = "checkbox";
    check.value = key;
    check.checked = action.proposed_payload.include_sections.includes(key);
    wrapper.prepend(check);
    sections.append(wrapper);
    checkboxes.push(check);
  }
  editor.append(sections);
  const noteLabel = element("label", "", "Comentario editorial humano (máximo 500 caracteres)");
  const note = element("textarea");
  note.maxLength = 500;
  note.rows = 3;
  note.value = action.proposed_payload.review_note;
  noteLabel.append(note);
  editor.append(noteLabel);
  article.append(editor);
  const controls = element("div", "review-controls");
  let busy = false;
  let retry = null;
  const editable = () => ({focus: focus.value, include_sections: checkboxes.filter(c => c.checked).map(c => c.value), review_note: note.value});
  const changed = () => JSON.stringify(editable()) !== JSON.stringify(action.proposed_payload);

  async function decide(decision) {
    if (busy) return;
    if (decision === "approve" && changed()) {
      live.textContent = "Guardá los cambios con Modificar antes de aprobar esa versión.";
      return;
    }
    const payload = {session_id: action.session_id, expected_version: action.version};
    if (decision === "modify") {
      payload.changes = editable();
      if (!payload.changes.include_sections.includes(payload.changes.focus)) {
        live.textContent = "Incluí la sección elegida como enfoque.";
        focus.focus();
        return;
      }
    }
    const signature = JSON.stringify({decision, payload});
    if (!retry || retry.signature !== signature) retry = {signature, key: crypto.randomUUID()};
    payload.idempotency_key = retry.key;
    busy = true;
    editor.disabled = true;
    for (const button of controls.querySelectorAll("button")) button.disabled = true;
    article.setAttribute("aria-busy", "true");
    live.textContent = "Guardando decisión…";
    try {
      const response = await fetch(`/agent/actions/${action.action_id}/${decision}`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (response.status === 409) {
        live.textContent = "La acción cambió o ya fue resuelta. Recuperando su estado…";
        await recoverAction(action.action_id, action.session_id);
        statusRegion.textContent = "Conflicto resuelto: revisá el estado actualizado antes de decidir.";
        return;
      }
      if (!response.ok) throw new UserFacingError(response.status === 422
        ? "La modificación no es válida. Revisá el enfoque, las secciones y el comentario."
        : "No se pudo guardar la decisión. Reintentá; se conservará la misma clave.");
      renderAction(data.action);
      statusRegion.textContent = data.message;
      if (data.result) renderPublishedReport(data.result);
    } catch (error) {
      live.textContent = error instanceof UserFacingError ? error.message : "No se pudo confirmar la decisión. Reintentá o recargá para recuperar su estado.";
    } finally {
      busy = false;
      editor.disabled = false;
      article.setAttribute("aria-busy", "false");
      for (const button of controls.querySelectorAll("button")) button.disabled = false;
    }
  }
  for (const [decision, label] of [["approve", "Aprobar"], ["modify", "Modificar"], ["reject", "Rechazar"]]) {
    const button = element("button", decision === "approve" ? "primary-button" : "secondary-button", label);
    button.type = "button";
    button.addEventListener("click", () => decide(decision));
    controls.append(button);
  }
  article.append(controls, element("p", "help-text", "Modificar crea otra versión pendiente. No cambia precios ni indicadores. Rechazar conserva la auditoría."));
  messages.append(article);
  title.focus();
  scrollToLatest();
}

async function recoverAction(actionId, ownerSession) {
  const response = await fetch(`/agent/actions/${actionId}?session_id=${encodeURIComponent(ownerSession)}`);
  if (!response.ok) {
    if (response.status === 404) clearActiveAction(actionId);
    throw new UserFacingError("No se pudo recuperar la revisión de esta sesión.");
  }
  const data = await response.json();
  renderAction(data.action);
  if (data.result) renderPublishedReport(data.result);
}

const savedActionId = sessionStorage.getItem(ACTION_KEY);
if (savedActionId && sessionId) {
  recoverAction(savedActionId, sessionId).catch(() => showError("No se pudo recuperar la revisión pendiente. Recargá para reintentar."));
}
