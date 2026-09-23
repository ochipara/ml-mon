// gmon Web Dashboard Client Logic

let activeSessionId = null;
let currentEventSource = null;
let allSessions = [];
let currentSessionDetail = null;
const renderedStepIds = new Set();

// Configure marked if loaded
if (window.marked) {
  marked.setOptions({
    gfm: true,
    breaks: true,
  });
}

// Built-in resilient markdown renderer
function renderMarkdown(text) {
  if (!text) return "";
  if (window.marked) {
    try {
      return marked.parse(text);
    } catch (e) {
      console.warn("Marked parse error, using fallback:", e);
    }
  }

  // Simple, safe fallback
  let html = escapeHtml(text);
  html = html.replace(/```([a-zA-Z0-9_]*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.split('\n\n').map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
  return html;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatBytes(bytes) {
  if (!bytes || isNaN(bytes)) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function formatDate(isoStr) {
  if (!isoStr) return "";
  return isoStr.replace("T", " ").substring(0, 19);
}

// Fetch session list
async function loadSessions() {
  try {
    const res = await fetch("/api/conversations");
    allSessions = await res.json();
    renderSessionList(allSessions);

    if (!activeSessionId && allSessions.length > 0) {
      selectSession(allSessions[0].id);
    }
  } catch (err) {
    console.error("Failed to load sessions:", err);
  }
}

function renderSessionList(sessions) {
  const container = document.getElementById("session-list");
  if (!sessions.length) {
    container.innerHTML = '<div class="loading-placeholder">No conversations found.</div>';
    return;
  }

  container.innerHTML = sessions
    .map((s) => {
      const isSelected = s.id === activeSessionId ? "active" : "";
      const statusBadge = s.is_active
        ? '<span class="badge-live">LIVE</span>'
        : '<span style="color: var(--text-dim);">○ IDLE</span>';
      const planBadge = s.has_plan ? "📋 Plan" : "";
      const shortId = s.id.substring(0, 8);
      const time = s.last_modified
        ? s.last_modified.replace("T", " ").substring(5, 16)
        : "";

      return `
      <div class="session-item ${isSelected}" onclick="selectSession('${s.id}')">
        <div class="session-item-header">
          <span class="session-item-id">${shortId}…</span>
          <span class="session-item-time">🕒 ${time}</span>
        </div>
        <div class="session-item-title" title="${escapeHtml(s.title)}">
          ${escapeHtml(s.title)}
        </div>
        <div class="session-item-footer">
          ${statusBadge}
          <span>⚡ ${s.step_count} steps</span>
          <span style="color: var(--accent-yellow); font-weight: 600;">${planBadge}</span>
        </div>
      </div>
    `;
    })
    .join("");
}

// Select a session and populate all tabs & live streaming
async function selectSession(sessionId) {
  if (activeSessionId === sessionId && currentEventSource) return;
  activeSessionId = sessionId;
  renderedStepIds.clear();

  // Highlight in sidebar
  renderSessionList(allSessions);

  // Update header
  const session = allSessions.find((s) => s.id === sessionId);
  if (session) {
    document.getElementById("active-session-title").innerText = session.title;
    document.getElementById("active-session-id").innerText = session.id;
    const dot = document.getElementById("session-status-dot");
    const statusText = document.getElementById("session-status-text");
    if (session.is_active) {
      dot.className = "pulse-dot live";
      statusText.innerText = "LIVE STREAMING";
    } else {
      dot.className = "pulse-dot idle";
      statusText.innerText = "COMPLETED";
    }
  }

  // Load initial detail
  const timelineContainer = document.getElementById("timeline-container");
  timelineContainer.innerHTML = '<div class="loading-placeholder">Loading conversation timeline...</div>';

  try {
    const res = await fetch(`/api/conversations/${sessionId}`);
    const detail = await res.json();
    currentSessionDetail = detail;
    timelineContainer.innerHTML = "";

    // 1. Update Model Badge
    const modelBadge = document.getElementById("active-session-model");
    const modelName = (detail.analytics && detail.analytics.model_name) ||
                      (detail.summary && detail.summary.model_name) ||
                      (session && session.model_name);
    if (modelName) {
      modelBadge.innerText = `🤖 ${modelName}`;
      modelBadge.style.display = "inline-flex";
    } else {
      modelBadge.innerText = `🤖 Default`;
      modelBadge.style.display = "inline-flex";
    }

    // 2. Render historical steps
    if (detail.steps && detail.steps.length) {
      for (const step of detail.steps) {
        appendStepToTimeline(step, false);
      }
    } else {
      timelineContainer.innerHTML = '<div class="empty-state">No steps in this conversation yet.</div>';
    }

    // 3. Render plan & walkthrough
    if (detail.plan) {
      updatePlanView(detail.plan);
    }

    // 4. Render Files Touched Tab
    renderFilesTouchedTab(detail.analytics);

    // 5. Render Media & Logs Tab
    renderMediaTab(detail.analytics);

    // 6. Render IDE Context & Analytics Tab
    renderContextTab(detail);

    // Apply active filters
    applyFilters();

    // Scroll to bottom on initial load if autoscroll is enabled
    if (document.getElementById("toggle-autoscroll").checked) {
      timelineContainer.scrollTop = timelineContainer.scrollHeight;
    }
  } catch (err) {
    timelineContainer.innerHTML = `<div class="empty-state">Failed to load session details: ${escapeHtml(err.message)}</div>`;
  }

  // Connect to SSE stream
  connectEventSource(sessionId);
}

function connectEventSource(sessionId) {
  if (currentEventSource) {
    currentEventSource.close();
  }

  currentEventSource = new EventSource(`/api/conversations/${sessionId}/stream`);

  currentEventSource.addEventListener("step", (e) => {
    try {
      const step = JSON.parse(e.data);
      appendStepToTimeline(step, true);
    } catch (err) {
      console.error("Error processing stream step:", err);
    }
  });

  currentEventSource.addEventListener("plan", (e) => {
    try {
      const plan = JSON.parse(e.data);
      updatePlanView(plan);
    } catch (err) {
      console.error("Error processing plan update:", err);
    }
  });

  currentEventSource.onerror = (err) => {
    console.warn("SSE stream connection issue, retrying...", err);
  };
}

// Append a step to timeline
function appendStepToTimeline(step, shouldScroll) {
  const container = document.getElementById("timeline-container");
  const stepKey = `step-${step.step_index}-${step.step_type}`;

  if (renderedStepIds.has(stepKey)) {
    return;
  }
  renderedStepIds.add(stepKey);

  const timeStr = step.created_at ? step.created_at.substring(11, 19) : "";
  const cards = [];

  // Check if this step is a checkpoint/compaction
  if (step.is_checkpoint || step.step_type === "CHECKPOINT") {
    const cpText = step.raw_content || step.user_prompt || "Session compacted / state checkpointed.";
    cards.push(`
      <div class="timeline-card card-checkpoint step-checkpoint" data-type="checkpoint" data-is-error="false" data-search="${escapeHtml(cpText.toLowerCase())}">
        <div class="card-header">
          <span>⚙️ <strong>System Checkpoint / Compaction</strong></span>
          <span class="tool-badge">Step ${step.step_index}${timeStr ? ' • 🕒 ' + timeStr : ''}</span>
        </div>
        <div class="card-body">
          <p class="dim-text">${renderMarkdown(cpText)}</p>
        </div>
      </div>
    `);
  }

  // 1. User Request
  if (step.user_prompt) {
    cards.push(`
      <div class="timeline-card card-user step-user" data-type="user" data-is-error="false" data-search="${escapeHtml(step.user_prompt.toLowerCase())}">
        <div class="card-header">
          <span>👤 <strong>User Request</strong></span>
          <span class="tool-badge">Step ${step.step_index}${timeStr ? ' • 🕒 ' + timeStr : ''}</span>
        </div>
        <div class="card-body markdown-body">
          ${renderMarkdown(step.user_prompt)}
        </div>
      </div>
    `);
  }

  // 2. Chain of Thought (CoT)
  if (step.thought && step.thought.content) {
    const durationText = step.thought.duration_seconds
      ? `<span class="cot-duration">⏱️ ${step.thought.duration_seconds.toFixed(1)}s</span>`
      : "";
    cards.push(`
      <div class="timeline-card card-cot step-cot" data-type="cot" data-is-error="false" data-search="${escapeHtml(step.thought.content.toLowerCase())}">
        <div class="card-header clickable" onclick="toggleCardBody('cot-body-${step.step_index}')">
          <span>🧠 <strong>Chain of Thought</strong></span>
          <div style="display: flex; align-items: center; gap: 8px;">
            ${durationText}
            <span class="cot-badge">${step.thought.content.length.toLocaleString()} chars</span>
            <span class="tool-badge">Step ${step.step_index}${timeStr ? ' • 🕒 ' + timeStr : ''}</span>
          </div>
        </div>
        <div class="card-body markdown-body" id="cot-body-${step.step_index}">
          ${renderMarkdown(step.thought.content)}
        </div>
      </div>
    `);
  }

  // 3. Tool Calls (Collapsible accordion, collapsed by default for compactness)
  if (step.tool_calls && step.tool_calls.length) {
    for (let i = 0; i < step.tool_calls.length; i++) {
      const tc = step.tool_calls[i];
      const summaryText = tc.summary ? ` — <em>${escapeHtml(tc.summary)}</em>` : "";
      const bodyId = `tool-call-${step.step_index}-${i}`;
      const searchContent = `${tc.name} ${tc.summary || ''} ${JSON.stringify(tc.args)}`.toLowerCase();

      cards.push(`
        <div class="timeline-card card-tool step-tool" data-type="tool" data-is-error="false" data-search="${escapeHtml(searchContent)}">
          <div class="card-header clickable" onclick="toggleCardBody('${bodyId}')">
            <span>
              <span class="tool-toggle-icon">▶</span>
              🛠️ <strong>Tool Call:</strong> <code>${escapeHtml(tc.name)}</code>${summaryText}
            </span>
            <span class="tool-badge">Step ${step.step_index}</span>
          </div>
          <div class="card-body" id="${bodyId}" style="display: none;">
            <pre><code>${escapeHtml(JSON.stringify(tc.args, null, 2))}</code></pre>
          </div>
        </div>
      `);
    }
  }

  // 4. Tool Result (Collapsible accordion, collapsed by default)
  if (step.tool_result && step.tool_result.content) {
    const bodyId = `tool-res-${step.step_index}`;
    const isError = step.is_error || (step.tool_result.exit_code !== 0 && step.tool_result.exit_code !== null) || step.status === "ERROR";
    const statusColor = !isError ? "var(--accent-green)" : "var(--accent-red)";
    const statusText = !isError ? "✔ Done" : `✖ Error (Exit ${step.tool_result.exit_code ?? 1})`;
    const errorClass = isError ? "is-error" : "";
    const durationText = step.tool_result.duration_seconds
      ? `<span class="tool-badge" style="margin-left: 6px;">⏱️ ${step.tool_result.duration_seconds.toFixed(1)}s</span>`
      : "";
    const searchContent = `${step.tool_result.tool_name} ${step.tool_result.content}`.toLowerCase();

    cards.push(`
      <div class="timeline-card card-tool step-tool ${errorClass}" data-type="tool" data-is-error="${isError}" data-search="${escapeHtml(searchContent)}">
        <div class="card-header clickable" onclick="toggleCardBody('${bodyId}')">
          <span>
            <span class="tool-toggle-icon">▶</span>
            📥 <strong>Tool Result:</strong> <code>${escapeHtml(step.tool_result.tool_name || "OUTPUT")}</code>
            <span style="color: ${statusColor}; font-weight: 600; margin-left: 8px;">${statusText}</span>
            ${durationText}
          </span>
          <span class="tool-badge">Step ${step.step_index}</span>
        </div>
        <div class="card-body" id="${bodyId}" style="display: none;">
          <pre><code>${escapeHtml(step.tool_result.content.substring(0, 2000))}${step.tool_result.content.length > 2000 ? "\n... [truncated]" : ""}</code></pre>
        </div>
      </div>
    `);
  }

  // 5. Assistant Response
  if (step.model_response) {
    cards.push(`
      <div class="timeline-card card-assistant step-assistant" data-type="assistant" data-is-error="false" data-search="${escapeHtml(step.model_response.toLowerCase())}">
        <div class="card-header">
          <span>🤖 <strong>Assistant Response</strong></span>
          <span class="tool-badge">Step ${step.step_index}${timeStr ? ' • 🕒 ' + timeStr : ''}</span>
        </div>
        <div class="card-body markdown-body">
          ${renderMarkdown(step.model_response)}
        </div>
      </div>
    `);
  }

  if (cards.length) {
    container.insertAdjacentHTML("beforeend", cards.join(""));
    applyFilters();
    if (shouldScroll && document.getElementById("toggle-autoscroll").checked) {
      container.scrollTop = container.scrollHeight;
    }
  }
}

// Update Plan & Walkthrough View
function updatePlanView(plan) {
  const planEl = document.getElementById("plan-content");
  const wtEl = document.getElementById("walkthrough-content");
  const planBadge = document.getElementById("plan-status-badge");
  const wtBadge = document.getElementById("wt-status-badge");

  if (plan.plan_content) {
    planEl.innerHTML = renderMarkdown(plan.plan_content);
    if (planBadge) planBadge.innerText = plan.plan_last_modified ? `Updated ${formatDate(plan.plan_last_modified)}` : "Available";
  } else {
    planEl.innerHTML = '<p class="dim-text">No implementation plan found for this session.</p>';
    if (planBadge) planBadge.innerText = "None";
  }

  if (plan.walkthrough_content) {
    wtEl.innerHTML = renderMarkdown(plan.walkthrough_content);
    if (wtBadge) wtBadge.innerText = plan.walkthrough_last_modified ? `Updated ${formatDate(plan.walkthrough_last_modified)}` : "Available";
  } else {
    wtEl.innerHTML = '<p class="dim-text">No walkthrough found for this session.</p>';
    if (wtBadge) wtBadge.innerText = "None";
  }
}

// Render Files Touched Tab
function renderFilesTouchedTab(analytics) {
  const container = document.getElementById("files-touched-list");
  const counter = document.getElementById("cnt-files");
  const files = (analytics && analytics.touched_files) || [];

  counter.innerText = files.length;

  if (!files.length) {
    container.innerHTML = '<div class="empty-state">No file modifications recorded in this session.</div>';
    return;
  }

  container.innerHTML = files.map(f => {
    const opClass = f.operation.toLowerCase() === "create" ? "create" : "modify";
    return `
      <div class="file-row">
        <div class="file-row-main">
          <span class="file-op-badge ${opClass}">${f.operation}</span>
          <span class="file-path" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
        </div>
        <div class="file-meta">
          <span class="tool-badge">Step ${f.step_index} • <code>${escapeHtml(f.tool_name)}</code></span>
        </div>
      </div>
    `;
  }).join("");
}

// Render Media & Logs Tab
function renderMediaTab(analytics) {
  const container = document.getElementById("media-artifacts-grid");
  const counter = document.getElementById("cnt-media");
  const media = (analytics && analytics.media_artifacts) || [];

  counter.innerText = media.length;

  if (!media.length) {
    container.innerHTML = '<div class="empty-state">No media artifacts generated in this session.</div>';
    return;
  }

  container.innerHTML = media.map(m => {
    if (m.media_type === "image") {
      return `
        <div class="media-card">
          <div class="media-preview">
            <img src="${m.relative_url}" alt="${escapeHtml(m.name)}" onclick="window.open('${m.relative_url}', '_blank')">
          </div>
          <div class="media-meta">
            <div class="media-title" title="${escapeHtml(m.name)}">🖼️ ${escapeHtml(m.name)}</div>
            <div class="dim-text">${formatBytes(m.size_bytes)} • ${formatDate(m.modified_at)}</div>
          </div>
        </div>
      `;
    } else if (m.media_type === "video") {
      return `
        <div class="media-card">
          <div class="media-preview">
            <video src="${m.relative_url}" controls preload="metadata" style="max-height: 100%; max-width: 100%;"></video>
          </div>
          <div class="media-meta">
            <div class="media-title" title="${escapeHtml(m.name)}">📹 ${escapeHtml(m.name)}</div>
            <div class="dim-text">${formatBytes(m.size_bytes)} • ${formatDate(m.modified_at)}</div>
          </div>
        </div>
      `;
    } else {
      return `
        <div class="media-card">
          <div class="media-preview" style="background: #0d1117; color: #58a6ff; font-family: var(--font-mono); font-size: 28px; display: flex; flex-direction: column; justify-content: center; align-items: center; cursor: pointer;" onclick="window.open('${m.relative_url}', '_blank')">
            <span>📜</span>
            <span style="font-size: 13px; color: var(--text-dim); margin-top: 8px;">View Log File</span>
          </div>
          <div class="media-meta">
            <div class="media-title" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</div>
            <div class="dim-text">${formatBytes(m.size_bytes)} • ${formatDate(m.modified_at)}</div>
          </div>
        </div>
      `;
    }
  }).join("");
}

// Render IDE Context & Analytics Tab
function renderContextTab(detail) {
  const env = detail.analytics && detail.analytics.environment;
  const toolCounts = (detail.analytics && detail.analytics.tool_counts) || {};
  const totalThoughts = (detail.analytics && detail.analytics.total_thoughts) || 0;
  const totalChars = (detail.analytics && detail.analytics.total_thinking_chars) || 0;
  const errors = (detail.analytics && detail.analytics.error_count) || 0;
  const checkpoints = (detail.analytics && detail.analytics.checkpoint_count) || 0;

  // 1. IDE State Body
  const ideEl = document.getElementById("ide-state-body");
  if (env) {
    let docsHtml = env.open_documents && env.open_documents.length
      ? `<ul>${env.open_documents.map(d => `<li><code>${escapeHtml(d)}</code></li>`).join("")}</ul>`
      : '<p class="dim-text">None</p>';

    let cmdsHtml = env.running_commands && env.running_commands.length
      ? `<ul>${env.running_commands.map(c => `<li><code>${escapeHtml(c)}</code></li>`).join("")}</ul>`
      : '<p class="dim-text">None</p>';

    ideEl.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div>
          <strong>Active Document:</strong>
          <div style="margin-top: 4px;"><code>${escapeHtml(env.active_document || "None")}</code> ${env.cursor_line ? `(Line ${env.cursor_line})` : ''}</div>
        </div>
        <div>
          <strong>Open Documents (${env.open_documents.length}):</strong>
          ${docsHtml}
        </div>
        <div>
          <strong>Running Commands (${env.running_commands.length}):</strong>
          ${cmdsHtml}
        </div>
      </div>
    `;
  } else {
    ideEl.innerHTML = '<p class="dim-text">No IDE state captured in prompt metadata.</p>';
  }

  // 2. Tool Breakdown Body
  const toolEl = document.getElementById("tool-breakdown-body");
  const toolEntries = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]);
  if (toolEntries.length) {
    toolEl.innerHTML = toolEntries.map(([name, count]) => `
      <div class="tool-bar-item">
        <span class="tool-bar-label">⚙️ ${escapeHtml(name)}</span>
        <span class="tool-bar-count">${count}</span>
      </div>
    `).join("");
  } else {
    toolEl.innerHTML = '<p class="dim-text">No tool invocations recorded.</p>';
  }

  // 3. Performance & Latency Body
  const perfEl = document.getElementById("session-perf-body");
  const avgChars = totalThoughts > 0 ? Math.round(totalChars / totalThoughts) : 0;
  perfEl.innerHTML = `
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px;">
      <div style="background: var(--bg-base); padding: 14px; border-radius: 8px; border: 1px solid var(--border-subtle);">
        <div class="dim-text" style="font-size: 12px; margin-bottom: 4px;">TOTAL STEPS</div>
        <div style="font-size: 22px; font-weight: 700; color: var(--accent-blue);">${detail.steps.length}</div>
      </div>
      <div style="background: var(--bg-base); padding: 14px; border-radius: 8px; border: 1px solid var(--border-subtle);">
        <div class="dim-text" style="font-size: 12px; margin-bottom: 4px;">THINKING BLOCKS</div>
        <div style="font-size: 22px; font-weight: 700; color: var(--accent-purple);">${totalThoughts}</div>
      </div>
      <div style="background: var(--bg-base); padding: 14px; border-radius: 8px; border: 1px solid var(--border-subtle);">
        <div class="dim-text" style="font-size: 12px; margin-bottom: 4px;">TOTAL COT CHARACTERS</div>
        <div style="font-size: 22px; font-weight: 700; color: var(--accent-purple);">${totalChars.toLocaleString()}</div>
      </div>
      <div style="background: var(--bg-base); padding: 14px; border-radius: 8px; border: 1px solid var(--border-subtle);">
        <div class="dim-text" style="font-size: 12px; margin-bottom: 4px;">AVG REASONING LENGTH</div>
        <div style="font-size: 22px; font-weight: 700; color: var(--accent-purple);">${avgChars.toLocaleString()} <span style="font-size: 12px; font-weight: 400;">chars/thought</span></div>
      </div>
      <div style="background: var(--bg-base); padding: 14px; border-radius: 8px; border: 1px solid var(--border-subtle);">
        <div class="dim-text" style="font-size: 12px; margin-bottom: 4px;">ERRORS DETECTED</div>
        <div style="font-size: 22px; font-weight: 700; color: ${errors > 0 ? '#f87171' : 'var(--text-dim)'};">${errors}</div>
      </div>
      <div style="background: var(--bg-base); padding: 14px; border-radius: 8px; border: 1px solid var(--border-subtle);">
        <div class="dim-text" style="font-size: 12px; margin-bottom: 4px;">CHECKPOINTS / COMPACTIONS</div>
        <div style="font-size: 22px; font-weight: 700; color: var(--text-secondary);">${checkpoints}</div>
      </div>
    </div>
  `;
}

// Master Filtering Logic
function applyFilters() {
  const searchInput = document.getElementById("timeline-search");
  const query = searchInput ? searchInput.value.toLowerCase().trim() : "";
  const showCoT = document.getElementById("toggle-cot") ? document.getElementById("toggle-cot").checked : true;
  const showTools = document.getElementById("toggle-tools") ? document.getElementById("toggle-tools").checked : true;
  const showCheckpoints = document.getElementById("toggle-checkpoints") ? document.getElementById("toggle-checkpoints").checked : true;
  const showErrorsOnly = document.getElementById("toggle-errors") ? document.getElementById("toggle-errors").checked : false;

  const cards = document.querySelectorAll("#timeline-container .timeline-card");

  cards.forEach(card => {
    const cardType = card.getAttribute("data-type");
    const isError = card.getAttribute("data-is-error") === "true";
    const searchContent = card.getAttribute("data-search") || "";

    let visible = true;

    // Filter by Errors Only
    if (showErrorsOnly && !isError) {
      visible = false;
    }

    // Filter by type toggles
    if (visible) {
      if (cardType === "cot" && !showCoT) visible = false;
      else if (cardType === "tool" && !showTools) visible = false;
      else if (cardType === "checkpoint" && !showCheckpoints) visible = false;
    }

    // Filter by search query
    if (visible && query.length > 0) {
      if (!searchContent.includes(query)) {
        visible = false;
      }
    }

    card.style.display = visible ? "" : "none";
  });
}

// Toggle card expansion (accordion)
function toggleCardBody(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const isHidden = el.style.display === "none";
  el.style.display = isHidden ? "block" : "none";

  // Update arrow icon if parent has one
  const parent = el.closest(".timeline-card");
  if (parent) {
    const icon = parent.querySelector(".tool-toggle-icon");
    if (icon) {
      icon.innerText = isHidden ? "▼" : "▶";
    }
  }
}

// Switch between Tabs
function switchTab(tab) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab-view").forEach((v) => v.classList.remove("active"));

  const filterBar = document.getElementById("timeline-filter-bar");

  if (tab === "timeline") {
    document.getElementById("tab-timeline").classList.add("active");
    document.getElementById("view-timeline").classList.add("active");
    if (filterBar) filterBar.style.display = "flex";
  } else if (tab === "plan") {
    document.getElementById("tab-plan").classList.add("active");
    document.getElementById("view-plan").classList.add("active");
    if (filterBar) filterBar.style.display = "none";
  } else if (tab === "files") {
    document.getElementById("tab-files").classList.add("active");
    document.getElementById("view-files").classList.add("active");
    if (filterBar) filterBar.style.display = "none";
  } else if (tab === "media") {
    document.getElementById("tab-media").classList.add("active");
    document.getElementById("view-media").classList.add("active");
    if (filterBar) filterBar.style.display = "none";
  } else if (tab === "context") {
    document.getElementById("tab-context").classList.add("active");
    document.getElementById("view-context").classList.add("active");
    if (filterBar) filterBar.style.display = "none";
  }
}

// Search sessions in sidebar
document.getElementById("session-search").addEventListener("input", (e) => {
  const query = e.target.value.toLowerCase();
  const filtered = allSessions.filter(
    (s) => s.id.toLowerCase().includes(query) || s.title.toLowerCase().includes(query)
  );
  renderSessionList(filtered);
});

// Initial load & poll sessions list every 5s
loadSessions();
setInterval(loadSessions, 5000);
