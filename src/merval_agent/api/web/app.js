"use strict";

const SESSION_KEY = "stock-analysis-session-id";
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
    input.focus();
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
