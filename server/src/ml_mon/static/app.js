// gmon Web Dashboard Client Logic

let activeSessionId = null;
let currentEventSource = null;
let allSessions = [];
let currentSessionDetail = null;
let currentContextReport = null;
let currentPromptSnapshot = null;
let contextBarMode = "relative";
let contextCapacityLimit = 1000000;
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
  // 1. Populate dropdown
  const dropdown = document.getElementById("session-dropdown");
  if (dropdown) {
    if (!sessions.length) {
      dropdown.innerHTML = '<option value="" disabled selected>No conversations found</option>';
    } else {
      dropdown.innerHTML = sessions.map(s => {
        const isSelected = s.id === activeSessionId ? "selected" : "";
        const statusMark = s.is_active ? "● LIVE: " : "";
        const time = s.last_modified ? s.last_modified.replace("T", " ").substring(5, 16) : "";
        const titleSnippet = s.title.length > 50 ? s.title.substring(0, 50) + "…" : s.title;
        return `<option value="${s.id}" ${isSelected}>${statusMark}${escapeHtml(titleSnippet)} (${s.step_count} steps • ${time})</option>`;
      }).join("");
    }
  }

  // 2. Populate recent session pills (up to 8)
  const strip = document.getElementById("recent-sessions-strip");
  if (strip) {
    const recent = sessions.slice(0, 8);
    strip.innerHTML = recent.map(s => {
      const isSelected = s.id === activeSessionId ? "active" : "";
      const liveDot = s.is_active ? '<span style="color: var(--accent-green); font-weight: bold;">●</span>' : '<span style="color: var(--text-dim);">○</span>';
      const shortTitle = s.title.length > 22 ? s.title.substring(0, 22) + "…" : s.title;
      return `
        <div class="session-pill ${isSelected}" onclick="selectSession('${s.id}')" title="${escapeHtml(s.title)} (${s.id})">
          ${liveDot}
          <span>${escapeHtml(shortTitle)}</span>
          <span style="color: var(--text-dim); font-size: 11px;">(${s.step_count})</span>
        </div>
      `;
    }).join("");
  }
}

function filterSessions() {
  const query = (document.getElementById("session-search").value || "").toLowerCase().trim();
  const liveOnly = document.getElementById("toggle-live-only").checked;

  const filtered = allSessions.filter(s => {
    if (liveOnly && !s.is_active) return false;
    if (query.length > 0) {
      const match = s.title.toLowerCase().includes(query) || s.id.toLowerCase().includes(query);
      if (!match) return false;
    }
    return true;
  });

  renderSessionList(filtered);
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

    // 7. If on Context & Usage tab, load it
    if (document.getElementById("tab-usage") && document.getElementById("tab-usage").classList.contains("active")) {
      loadContextWindow(sessionId);
    }

    // 8. If on Full Prompt tab, load it
    if (document.getElementById("tab-prompt") && document.getElementById("tab-prompt").classList.contains("active")) {
      loadPromptView(sessionId);
    }

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
    const estSummaryTokens = Math.ceil(cpText.length / 4);
    cards.push(`
      <div class="timeline-card card-checkpoint step-checkpoint" data-type="checkpoint" data-is-error="false" data-search="${escapeHtml(cpText.toLowerCase())}">
        <div class="card-header">
          <span>⚙️ <strong>System Checkpoint / Compaction</strong></span>
          <span class="tool-badge">Step ${step.step_index}${timeStr ? ' • 🕒 ' + timeStr : ''}</span>
        </div>
        <div class="card-body">
          <p class="dim-text">${renderMarkdown(cpText)}</p>
          <div class="checkpoint-context-bar">
            <div class="checkpoint-context-header">
              <span>⚡ <strong>Compaction Context Boundary:</strong> Context attention reset to baseline summary</span>
              <span class="tool-badge" style="color: var(--accent-yellow); font-weight: 600;">~${estSummaryTokens.toLocaleString()} tokens in summary</span>
            </div>
            <div class="mini-context-bar">
              <div class="mini-bar-segment" style="width: 100%; background-color: #6b7280;" title="Compaction Baseline Summary: ~${estSummaryTokens.toLocaleString()} tokens"></div>
            </div>
          </div>
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
  } else if (tab === "usage") {
    document.getElementById("tab-usage").classList.add("active");
    document.getElementById("view-usage").classList.add("active");
    if (filterBar) filterBar.style.display = "none";
    loadContextWindow(activeSessionId);
  } else if (tab === "prompt") {
    document.getElementById("tab-prompt").classList.add("active");
    document.getElementById("view-prompt").classList.add("active");
    if (filterBar) filterBar.style.display = "none";
    loadPromptView(activeSessionId);
  }
}

// Load Context Window & Token Usage Report
async function loadContextWindow(sessionId) {
  if (!sessionId) return;
  const listEl = document.getElementById("context-frames-list");
  listEl.innerHTML = '<div class="loading-placeholder">Loading context window report...</div>';

  try {
    const res = await fetch(`/api/conversations/${sessionId}/context`);
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const report = await res.json();
    currentContextReport = report;

    // 1. Metric Cards
    document.getElementById("usage-active-tokens").innerText = report.total_active_tokens.toLocaleString();
    document.getElementById("usage-active-chars").innerText = `${report.total_active_chars.toLocaleString()} characters`;
    document.getElementById("usage-total-tokens").innerText = report.total_session_tokens.toLocaleString();
    document.getElementById("usage-total-chars").innerText = `${report.total_session_chars.toLocaleString()} characters`;

    const statusEl = document.getElementById("usage-compaction-status");
    const boundaryEl = document.getElementById("usage-active-boundary");
    if (report.has_compaction) {
      statusEl.innerText = `Compacted (${report.compaction_count}x)`;
      statusEl.className = "stat-val yellow";
      boundaryEl.innerText = `Active from Step ${report.active_window_start_step}`;
    } else {
      statusEl.innerText = "Full History";
      statusEl.className = "stat-val green";
      boundaryEl.innerText = "No compactions triggered";
    }

    const activeFramesCount = report.frames.filter((f) => f.is_active).length;
    document.getElementById("usage-active-frames").innerText = activeFramesCount.toLocaleString();
    document.getElementById("usage-total-frames").innerText = `of ${report.frames.length.toLocaleString()} total session frames`;

    // 2. Stacked Utilization Progress Bar
    renderStackedUsageBar();

    // 3. Step-by-Step Prompt & Context Evolution Chart
    renderEvolutionChart();

    // 4. Render Frames
    filterContextFrames();
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Failed to load context report: ${escapeHtml(err.message)}</div>`;
  }
}

function setContextBarMode(mode) {
  contextBarMode = mode;
  const btnRel = document.getElementById("btn-mode-relative");
  const btnAbs = document.getElementById("btn-mode-absolute");
  const selectLimit = document.getElementById("select-capacity-limit");
  const titleEl = document.getElementById("usage-bar-title");
  const subtitleEl = document.getElementById("usage-bar-subtitle");

  if (mode === "relative") {
    btnRel.classList.add("active");
    btnAbs.classList.remove("active");
    if (selectLimit) selectLimit.style.display = "none";
    if (titleEl) titleEl.innerText = "Active Context Window Distribution";
    if (subtitleEl) subtitleEl.innerText = "Relative share (%) of active tokens across components";
  } else {
    btnRel.classList.remove("active");
    btnAbs.classList.add("active");
    if (selectLimit) selectLimit.style.display = "inline-block";
    if (titleEl) titleEl.innerText = "Context Window Capacity Utilization";
    if (subtitleEl) subtitleEl.innerText = `Active tokens versus model capacity limit (${contextCapacityLimit.toLocaleString()} tokens)`;
  }

  renderStackedUsageBar();
}

function updateContextCapacityLimit(val) {
  contextCapacityLimit = parseInt(val, 10) || 1000000;
  const subtitleEl = document.getElementById("usage-bar-subtitle");
  if (subtitleEl && contextBarMode === "absolute") {
    subtitleEl.innerText = `Active tokens versus model capacity limit (${contextCapacityLimit.toLocaleString()} tokens)`;
  }
  renderStackedUsageBar();
}

function renderStackedUsageBar() {
  if (!currentContextReport) return;
  const barEl = document.getElementById("usage-stacked-bar");
  const legendEl = document.getElementById("usage-stacked-legend");
  if (!barEl || !legendEl) return;

  const catColors = {
    system_instruction: "#ec4899",
    tool_declarations: "#8b5cf6",
    compaction_summary: "#9ca3af",
    user_prompts: "#10b981",
    cot_reasoning: "#a855f7",
    tool_outputs: "#f59e0b",
    assistant_responses: "#06b6d4",
    system_history: "#3b82f6",
  };

  const segments = [];
  const legends = [];
  const totalActive = currentContextReport.total_active_tokens;

  if (contextBarMode === "relative") {
    for (const b of currentContextReport.breakdown) {
      if (b.percentage > 0) {
        const color = catColors[b.category] || "#6366f1";
        segments.push(`
          <div class="bar-segment" style="width: ${b.percentage}%; background-color: ${color};" title="${escapeHtml(b.label)}: ${b.est_tokens.toLocaleString()} tokens (${b.percentage}%)"></div>
        `);
        legends.push(`
          <div class="legend-item">
            <span class="legend-dot" style="background-color: ${color};"></span>
            <span><strong>${escapeHtml(b.label)}</strong>: ${b.est_tokens.toLocaleString()} tokens (${b.percentage}%)</span>
          </div>
        `);
      }
    }
  } else {
    // Absolute Capacity mode
    const capacity = contextCapacityLimit;
    const usedPct = Math.min(100, (totalActive / capacity) * 100);

    for (const b of currentContextReport.breakdown) {
      if (b.est_tokens > 0) {
        const segPct = (b.est_tokens / capacity) * 100;
        const color = catColors[b.category] || "#6366f1";
        segments.push(`
          <div class="bar-segment" style="width: ${segPct}%; background-color: ${color};" title="${escapeHtml(b.label)}: ${b.est_tokens.toLocaleString()} tokens (${segPct.toFixed(1)}% of capacity)"></div>
        `);
        legends.push(`
          <div class="legend-item">
            <span class="legend-dot" style="background-color: ${color};"></span>
            <span><strong>${escapeHtml(b.label)}</strong>: ${b.est_tokens.toLocaleString()} tokens (${segPct.toFixed(1)}%)</span>
          </div>
        `);
      }
    }

    // Remaining Headroom segment
    const headroomPct = Math.max(0, 100 - usedPct);
    const headroomTokens = Math.max(0, capacity - totalActive);
    segments.push(`
      <div class="bar-segment" style="width: ${headroomPct}%; background-color: rgba(255, 255, 255, 0.06);" title="Available Headroom: ${headroomTokens.toLocaleString()} tokens (${headroomPct.toFixed(1)}%)"></div>
    `);
    legends.push(`
      <div class="legend-item" style="opacity: 0.7;">
        <span class="legend-dot" style="background-color: rgba(255, 255, 255, 0.2);"></span>
        <span><strong>Available Headroom</strong>: ${headroomTokens.toLocaleString()} tokens (${headroomPct.toFixed(1)}%)</span>
      </div>
    `);
  }

  barEl.innerHTML = segments.join("");
  legendEl.innerHTML = legends.join("");
}

let evolutionChartMode = "active";

function setEvolutionChartMode(mode) {
  evolutionChartMode = mode;
  const btnActive = document.getElementById("btn-chart-active");
  const btnCumul = document.getElementById("btn-chart-cumulative");
  const subtitle = document.getElementById("evolution-chart-subtitle");

  if (mode === "active") {
    btnActive?.classList.add("active");
    btnCumul?.classList.remove("active");
    if (subtitle) {
      subtitle.innerText = "Step-by-step active prompt window showing tool spikes, CoT growth, and compaction cliff drops";
    }
  } else {
    btnActive?.classList.remove("active");
    btnCumul?.classList.add("active");
    if (subtitle) {
      subtitle.innerText = "Cumulative total token consumption and session history across all interactions";
    }
  }

  renderEvolutionChart();
}

function renderEvolutionChart() {
  const container = document.getElementById("evolution-chart-container");
  const svg = document.getElementById("evolution-svg");
  const legendEl = document.getElementById("evolution-legend");
  const statsEl = document.getElementById("evolution-stats-summary");

  if (!svg || !currentContextReport?.evolution) {
    if (svg) svg.innerHTML = '<text x="500" y="160" fill="#64748b" text-anchor="middle" font-size="14">No evolution data available</text>';
    return;
  }

  const evo = currentContextReport.evolution;
  const points = evo.points;
  if (!points || points.length === 0) {
    svg.innerHTML = '<text x="500" y="160" fill="#64748b" text-anchor="middle" font-size="14">No step points recorded</text>';
    return;
  }

  const svgWidth = 1000;
  const svgHeight = 320;
  const padL = 65;
  const padR = 25;
  const padT = 25;
  const padB = 35;
  const plotW = svgWidth - padL - padR;
  const plotH = svgHeight - padT - padB;

  const yMax = evolutionChartMode === "active"
    ? Math.max(10000, Math.ceil((evo.max_active_tokens * 1.1) / 10000) * 10000)
    : Math.max(10000, Math.ceil((evo.max_cumulative_tokens * 1.05) / 10000) * 10000);

  const N = points.length;
  const getX = (idx) => padL + (idx / Math.max(1, N - 1)) * plotW;
  const getY = (val) => padT + plotH - (Math.max(0, val) / yMax) * plotH;

  // Categories in stacking order (bottom to top)
  const catOrder = [
    { key: "system_instruction", color: "#ec4899", label: "System Persona & Skills" },
    { key: "tool_declarations", color: "#8b5cf6", label: "Tool Schemas" },
    { key: "compaction_summary", color: "#9ca3af", label: "Compaction Memory" },
    { key: "user_prompts", color: "#10b981", label: "User Requests" },
    { key: "cot_reasoning", color: "#a855f7", label: "CoT Reasoning" },
    { key: "tool_outputs", color: "#f59e0b", label: "Tool Outputs & Diffs" },
    { key: "assistant_responses", color: "#06b6d4", label: "Assistant Responses" },
    { key: "system_history", color: "#3b82f6", label: "System History" },
  ];

  let svgElements = [];

  // 1. Background Grid & Token Y-Axis Labels
  const gridTicks = 4;
  for (let g = 0; g <= gridTicks; g++) {
    const val = Math.round((yMax / gridTicks) * g);
    const yPos = getY(val);
    const label = val >= 1000 ? `${Math.round(val / 1000)}k` : `${val}`;
    svgElements.push(`
      <line x1="${padL}" y1="${yPos}" x2="${padL + plotW}" y2="${yPos}" stroke="rgba(255, 255, 255, 0.07)" stroke-dasharray="3,3" />
      <text x="${padL - 10}" y="${yPos + 4}" fill="#64748b" font-size="11" font-family="monospace" text-anchor="end">${label}</text>
    `);
  }

  // 2. Generate Stacked Area Layers
  if (evolutionChartMode === "active") {
    let baselineY = new Array(N).fill(0);

    for (const cat of catOrder) {
      const topPoints = [];
      const bottomPoints = [];
      let catHasValues = false;

      for (let i = 0; i < N; i++) {
        const p = points[i];
        const val = p.breakdown?.[cat.key] || 0;
        if (val > 0) catHasValues = true;

        const bY = baselineY[i];
        const tY = bY + val;

        const px = getX(i);
        const pyTop = getY(tY);
        const pyBottom = getY(bY);

        topPoints.push(`${px.toFixed(1)},${pyTop.toFixed(1)}`);
        bottomPoints.unshift(`${px.toFixed(1)},${pyBottom.toFixed(1)}`);

        baselineY[i] = tY;
      }

      if (catHasValues) {
        const polyPoints = [...topPoints, ...bottomPoints].join(" ");
        svgElements.push(`
          <polygon points="${polyPoints}" fill="${cat.color}" fill-opacity="0.82" />
        `);
      }
    }

    // Top contour stroke
    const contourPoints = points.map((p, i) => `${getX(i).toFixed(1)},${getY(p.active_tokens).toFixed(1)}`).join(" ");
    svgElements.push(`
      <polyline points="${contourPoints}" fill="none" stroke="rgba(255, 255, 255, 0.95)" stroke-width="1.8" />
    `);
  } else {
    // Cumulative Mode: Single smooth cumulative area
    const polyPoints = [];
    polyPoints.push(`${padL},${padT + plotH}`);
    for (let i = 0; i < N; i++) {
      polyPoints.push(`${getX(i).toFixed(1)},${getY(points[i].cumulative_tokens).toFixed(1)}`);
    }
    polyPoints.push(`${(padL + plotW).toFixed(1)},${padT + plotH}`);

    svgElements.push(`
      <polygon points="${polyPoints.join(" ")}" fill="url(#cumul-gradient)" fill-opacity="0.8" />
      <polyline points="${points.map((p, i) => `${getX(i).toFixed(1)},${getY(p.cumulative_tokens).toFixed(1)}`).join(" ")}" fill="none" stroke="#38bdf8" stroke-width="2" />
    `);
  }

  // 3. Compaction Checkpoint Markers
  if (evo.checkpoints && evo.checkpoints.length > 0) {
    for (const ckptStep of evo.checkpoints) {
      const idx = points.findIndex(p => p.step_index === ckptStep);
      if (idx !== -1) {
        const cx = getX(idx);
        const p = points[idx];
        const cy = getY(p.active_tokens);
        svgElements.push(`
          <line x1="${cx}" y1="${padT}" x2="${cx}" y2="${padT + plotH}" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4,3" />
          <circle cx="${cx}" cy="${cy}" r="4" fill="#f59e0b" stroke="#ffffff" stroke-width="1.5" />
          <text x="${cx}" y="${padT - 6}" fill="#f59e0b" font-size="10" font-weight="600" text-anchor="middle">⚙️ Step ${ckptStep}</text>
        `);
      }
    }
  }

  // 4. X-Axis Step Labels
  const xTicks = 5;
  for (let k = 0; k <= xTicks; k++) {
    const idx = Math.min(N - 1, Math.round((k / xTicks) * (N - 1)));
    const stepVal = points[idx].step_index;
    const xPos = getX(idx);
    svgElements.push(`
      <text x="${xPos}" y="${padT + plotH + 18}" fill="#64748b" font-size="11" font-family="monospace" text-anchor="middle">Step ${stepVal}</text>
    `);
  }

  // Gradient definition
  const defs = `
    <defs>
      <linearGradient id="cumul-gradient" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.85"/>
        <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.2"/>
      </linearGradient>
    </defs>
  `;

  svg.innerHTML = defs + svgElements.join("");

  // 5. Render Legend
  if (legendEl) {
    legendEl.innerHTML = catOrder.map(c => `
      <div class="legend-item">
        <span class="legend-dot" style="background-color: ${c.color};"></span>
        <span>${escapeHtml(c.label)}</span>
      </div>
    `).join("");
  }

  // 6. Summary Stats in Footer
  if (statsEl) {
    const lastP = points[points.length - 1];
    statsEl.innerHTML = `
      <span class="evolution-stat-pill"><strong>Peak Active:</strong> ${evo.max_active_tokens.toLocaleString()} tokens</span>
      <span class="evolution-stat-pill"><strong>Current Active:</strong> ${lastP.active_tokens.toLocaleString()} tokens</span>
      <span class="evolution-stat-pill"><strong>Compactions:</strong> ${evo.checkpoints.length} cliff drops</span>
      <span class="evolution-stat-pill"><strong>Total Turns:</strong> ${evo.total_steps} steps</span>
    `;
  }

  // 7. Interactive Scrubber & Tooltip Listeners
  if (container && !container._hasScrubberListeners) {
    container._hasScrubberListeners = true;

    container.addEventListener("mousemove", (e) => {
      const rep = currentContextReport?.evolution;
      if (!rep || !rep.points || rep.points.length === 0) return;
      const pts = rep.points;
      const rect = container.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;

      const pW = (plotW / svgWidth) * rect.width;
      const pL = (padL / svgWidth) * rect.width;

      const ratio = Math.max(0, Math.min(1, (mouseX - pL) / pW));
      const idx = Math.min(pts.length - 1, Math.max(0, Math.round(ratio * (pts.length - 1))));
      const pt = pts[idx];

      const scrubberEl = document.getElementById("evolution-scrubber-line");
      const tooltipEl = document.getElementById("evolution-tooltip");
      if (scrubberEl) {
        scrubberEl.style.left = `${mouseX}px`;
        scrubberEl.style.display = "block";
      }

      if (tooltipEl) {
        const isCkpt = pt.is_checkpoint ? ' <span style="color: #f59e0b; font-weight: bold;">(⚙️ Compaction Cliff)</span>' : '';
        const deltaFormatted = pt.delta_tokens > 0 ? `+${pt.delta_tokens.toLocaleString()}` : `${pt.delta_tokens.toLocaleString()}`;

        const bd = pt.breakdown || {};
        const breakdownLines = catOrder
          .filter(c => (bd[c.key] || 0) > 0)
          .map(c => `
            <div class="evolution-tooltip-metric">
              <span style="color: ${c.color};">● ${escapeHtml(c.label)}:</span>
              <span style="font-family: monospace;">${(bd[c.key] || 0).toLocaleString()} t</span>
            </div>
          `).join("");

        tooltipEl.innerHTML = `
          <div class="evolution-tooltip-header">
            <span>Step ${pt.step_index}${isCkpt}</span>
            <span style="color: var(--accent-green);">${deltaFormatted} t</span>
          </div>
          <div style="font-size: 11.5px; color: var(--text-secondary); margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(pt.title)}</div>
          <div class="evolution-tooltip-metric">
            <strong>Active Prompt:</strong>
            <strong style="color: #f472b6;">${pt.active_tokens.toLocaleString()} tokens</strong>
          </div>
          <div class="evolution-tooltip-metric">
            <span class="dim-text">Cumulative Session:</span>
            <span style="font-family: monospace;">${pt.cumulative_tokens.toLocaleString()} tokens</span>
          </div>
          <div class="evolution-tooltip-breakdown">
            ${breakdownLines}
          </div>
        `;

        tooltipEl.style.display = "block";
        const tipW = 280;
        let tipLeft = mouseX + 15;
        if (tipLeft + tipW > rect.width) {
          tipLeft = mouseX - tipW - 15;
        }
        tooltipEl.style.left = `${Math.max(10, tipLeft)}px`;
        tooltipEl.style.top = "15px";
      }
    });

    container.addEventListener("mouseleave", () => {
      const scrubberEl = document.getElementById("evolution-scrubber-line");
      const tooltipEl = document.getElementById("evolution-tooltip");
      if (scrubberEl) scrubberEl.style.display = "none";
      if (tooltipEl) tooltipEl.style.display = "none";
    });

    container.addEventListener("click", (e) => {
      const rep = currentContextReport?.evolution;
      if (!rep || !rep.points || rep.points.length === 0) return;
      const pts = rep.points;
      const rect = container.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const pW = (plotW / svgWidth) * rect.width;
      const pL = (padL / svgWidth) * rect.width;
      const ratio = Math.max(0, Math.min(1, (mouseX - pL) / pW));
      const idx = Math.min(pts.length - 1, Math.max(0, Math.round(ratio * (pts.length - 1))));
      const pt = pts[idx];

      const searchBox = document.getElementById("frame-search");
      if (searchBox) {
        searchBox.value = `Step ${pt.step_index}`;
        filterContextFrames();
        searchBox.scrollIntoView({ behavior: "smooth" });
      }
    });
  }
}


function scrollToBottom() {
  scrollToViewBottom("timeline-container");
}

function scrollToViewBottom(containerId) {
  const c = document.getElementById(containerId);
  if (c) {
    c.scrollTo({ top: c.scrollHeight, behavior: "smooth" });
  }
}

function handleTimelineScroll() {
  handleViewScroll(document.getElementById("timeline-container"), "fab-scroll-bottom");
}

function handleViewScroll(container, fabId) {
  const fab = typeof fabId === "string" ? document.getElementById(fabId) : fabId;
  if (!container || !fab) return;
  const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
  if (distanceFromBottom > 250) {
    fab.style.display = "flex";
  } else {
    fab.style.display = "none";
  }
}

function filterContextFrames() {
  if (!currentContextReport || !currentContextReport.frames) return;
  const listEl = document.getElementById("context-frames-list");
  const query = (document.getElementById("frame-search").value || "").toLowerCase().trim();
  const activeOnly = document.getElementById("toggle-active-only").checked;

  const filtered = currentContextReport.frames.filter((f) => {
    if (activeOnly && !f.is_active) return false;
    if (query.length > 0) {
      const match = f.title.toLowerCase().includes(query) ||
                    f.preview.toLowerCase().includes(query) ||
                    f.full_content.toLowerCase().includes(query) ||
                    f.frame_type.toLowerCase().includes(query);
      if (!match) return false;
    }
    return true;
  });

  if (!filtered.length) {
    listEl.innerHTML = '<div class="empty-state">No matching context frames found.</div>';
    return;
  }

  listEl.innerHTML = filtered.map((f) => {
    const bodyId = `frame-body-${f.index}`;
    const prunedClass = f.is_active ? "" : "pruned";
    const statusBadge = f.is_active
      ? '<span class="tool-badge" style="color: var(--accent-green); font-weight: 600;">ACTIVE</span>'
      : '<span class="tool-badge" style="color: var(--text-dim);">PRUNED</span>';

    return `
      <div class="frame-card ${prunedClass}">
        <div class="frame-header" onclick="toggleCardBody('${bodyId}')">
          <div class="frame-header-left">
            <span class="tool-toggle-icon">▶</span>
            <strong>#${f.index}</strong>
            <span>${escapeHtml(f.title)}</span>
          </div>
          <div class="frame-header-right">
            ${statusBadge}
            <span class="frame-token-badge">⚡ ${f.est_tokens.toLocaleString()} tokens</span>
            <span class="dim-text" style="font-size: 12px;">${f.char_count.toLocaleString()} chars</span>
          </div>
        </div>
        <div class="frame-body" id="${bodyId}" style="display: none;">
          <pre><code>${escapeHtml(f.full_content)}</code></pre>
        </div>
      </div>
    `;
  }).join("");
}

// ==========================================
// Full Prompt View & Reconstructor Functions
// ==========================================

async function loadPromptView(sessionId) {
  if (!sessionId) return;
  const listEl = document.getElementById("prompt-sections-list");
  if (!listEl) return;
  listEl.innerHTML = '<div class="loading-placeholder">Reconstructing full model prompt snapshot...</div>';

  const downloadBtn = document.getElementById("btn-download-prompt");
  if (downloadBtn) {
    downloadBtn.href = `/api/conversations/${sessionId}/prompt/raw?download=true`;
  }

  try {
    const res = await fetch(`/api/conversations/${sessionId}/prompt`);
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const snapshot = await res.json();
    currentPromptSnapshot = snapshot;

    // 1. Metric Cards
    const totalToks = snapshot.total_est_tokens || snapshot.est_tokens || 0;
    const totalChars = snapshot.total_chars || snapshot.total_characters || 0;
    document.getElementById("prompt-total-tokens").innerText = totalToks.toLocaleString();
    document.getElementById("prompt-total-chars").innerText = `${totalChars.toLocaleString()} characters`;

    const sysSec = snapshot.sections.find(s => s.category === "system_instruction");
    const skillsSec = snapshot.sections.find(s => s.category === "skills_plugins");
    const sysTokens = (sysSec?.est_tokens || 0) + (skillsSec?.est_tokens || 0);
    const sysChars = (sysSec?.char_count || 0) + (skillsSec?.char_count || 0);
    document.getElementById("prompt-system-tokens").innerText = sysTokens.toLocaleString();
    document.getElementById("prompt-system-chars").innerText = `${sysChars.toLocaleString()} characters`;

    const toolsSec = snapshot.sections.find(s => s.category === "tools");
    document.getElementById("prompt-tools-tokens").innerText = (toolsSec?.est_tokens || 0).toLocaleString();
    document.getElementById("prompt-tools-count").innerText = `${snapshot.tools?.length || 0} tools declared`;

    const compSec = snapshot.sections.find(s => s.category === "environment_memory");
    const histSec = snapshot.sections.find(s => s.category === "conversation_history");
    const histTokens = (compSec?.est_tokens || 0) + (histSec?.est_tokens || 0);
    const histChars = (compSec?.char_count || 0) + (histSec?.char_count || 0);
    document.getElementById("prompt-history-tokens").innerText = histTokens.toLocaleString();
    document.getElementById("prompt-history-chars").innerText = `${histChars.toLocaleString()} characters`;

    // 2. Render Section Quick Jump Pills
    renderPromptPills();

    // 3. Render Collapsible Section Cards
    renderPromptSections(snapshot.sections);
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Failed to reconstruct full prompt: ${escapeHtml(err.message)}</div>`;
  }
}

function renderPromptPills() {
  const pillsEl = document.getElementById("prompt-section-pills");
  if (!pillsEl || !currentPromptSnapshot) return;

  const pillIcons = {
    system_instruction: "🧠",
    skills_plugins: "🧩",
    tools: "🛠️",
    environment_memory: "⚙️",
    conversation_history: "💬",
  };

  pillsEl.innerHTML = currentPromptSnapshot.sections.map((s) => {
    const icon = pillIcons[s.category] || "📄";
    return `
      <button class="prompt-pill" onclick="scrollToPromptSection('${s.id}')" title="Jump to ${escapeHtml(s.title)}">
        <span>${icon}</span>
        <span>${escapeHtml(s.title)}</span>
        <span class="pill-tokens">(${s.est_tokens.toLocaleString()}t)</span>
      </button>
    `;
  }).join("");
}

function renderPromptSections(sections) {
  const listEl = document.getElementById("prompt-sections-list");
  if (!listEl) return;

  if (!sections || sections.length === 0) {
    listEl.innerHTML = '<div class="empty-state">No prompt snapshot data found for this session.</div>';
    return;
  }

  listEl.innerHTML = sections.map((sec, idx) => {
    const cardId = `prompt-card-${sec.id}`;
    // Expand the first section by default
    const isExpanded = idx === 0;
    const collapsedClass = isExpanded ? "" : "collapsed";

    let extraContent = "";
    if (sec.category === "tools" && currentPromptSnapshot.tools && currentPromptSnapshot.tools.length > 0) {
      extraContent = `
        <div style="margin-bottom: 16px;">
          <h4 style="font-size: 13px; color: var(--text-secondary); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px;">Structured Tool Schemas (${currentPromptSnapshot.tools.length})</h4>
          <div class="tool-schema-list">
            ${currentPromptSnapshot.tools.map(tool => {
              const toolId = `tool-schema-${tool.name}`;
              return `
                <div class="tool-schema-card collapsed" id="${toolId}">
                  <div class="tool-schema-header" onclick="toggleToolSchema('${tool.name}')">
                    <div>
                      <span class="tool-schema-name">${escapeHtml(tool.name)}</span>
                      <div class="tool-schema-desc">${escapeHtml(tool.description)}</div>
                    </div>
                    <span class="prompt-card-chevron tool-schema-chevron">▼</span>
                  </div>
                  <div class="tool-schema-body">
                    <pre><code>${escapeHtml(JSON.stringify(tool.parameters_schema || {}, null, 2))}</code></pre>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        </div>
        <h4 style="font-size: 13px; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Raw Declarations Text</h4>
      `;
    }

    return `
      <div class="prompt-card ${collapsedClass}" id="${cardId}">
        <div class="prompt-card-header" onclick="togglePromptSection('${sec.id}')">
          <div class="prompt-card-title-group">
            <span class="prompt-card-chevron">▼</span>
            <span class="prompt-card-title">${escapeHtml(sec.title)}</span>
            <span class="prompt-card-badge">${escapeHtml(sec.category)}</span>
          </div>
          <div class="prompt-card-actions" onclick="event.stopPropagation()">
            <span class="prompt-token-pill">⚡ ${(sec.est_tokens || 0).toLocaleString()} tokens</span>
            <span class="dim-text" style="font-size: 12px;">${(sec.char_count || 0).toLocaleString()} chars</span>
            <button class="btn-card-copy" onclick="copySectionText('${sec.id}', this)" title="Copy Section Content">
              <span>📋</span> Copy
            </button>
          </div>
        </div>
        <div class="prompt-card-body">
          ${extraContent}
          <pre class="prompt-code-block"><code>${escapeHtml(sec.content)}</code></pre>
        </div>
      </div>
    `;
  }).join("");
}

function togglePromptSection(sectionId) {
  const card = document.getElementById(`prompt-card-${sectionId}`);
  if (card) {
    card.classList.toggle("collapsed");
  }
}

function toggleToolSchema(toolName) {
  const card = document.getElementById(`tool-schema-${toolName}`);
  if (card) {
    card.classList.toggle("collapsed");
  }
}

function scrollToPromptSection(sectionId) {
  const card = document.getElementById(`prompt-card-${sectionId}`);
  if (card) {
    if (card.classList.contains("collapsed")) {
      card.classList.remove("collapsed");
    }
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function filterPromptContent() {
  if (!currentPromptSnapshot) return;
  const query = (document.getElementById("prompt-search").value || "").toLowerCase().trim();

  currentPromptSnapshot.sections.forEach(sec => {
    const card = document.getElementById(`prompt-card-${sec.id}`);
    if (!card) return;
    if (!query) {
      card.style.display = "";
      return;
    }
    const match = sec.title.toLowerCase().includes(query) ||
                  sec.category.toLowerCase().includes(query) ||
                  sec.content.toLowerCase().includes(query);
    card.style.display = match ? "" : "none";
    if (match && card.classList.contains("collapsed")) {
      card.classList.remove("collapsed");
    }
  });
}

async function copyFullPrompt() {
  if (!activeSessionId) return;
  const btn = document.getElementById("btn-copy-prompt");
  const textEl = document.getElementById("copy-prompt-text");
  const iconEl = document.getElementById("copy-prompt-icon");
  try {
    const res = await fetch(`/api/conversations/${activeSessionId}/prompt/raw`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    await navigator.clipboard.writeText(text);
    if (textEl) textEl.innerText = "Copied Full Prompt!";
    if (iconEl) iconEl.innerText = "✓";
    if (btn) btn.style.borderColor = "var(--accent-green)";
    setTimeout(() => {
      if (textEl) textEl.innerText = "Copy Full Prompt";
      if (iconEl) iconEl.innerText = "📋";
      if (btn) btn.style.borderColor = "";
    }, 2000);
  } catch (err) {
    alert("Failed to copy full prompt: " + err.message);
  }
}

function copySectionText(sectionId, btnEl) {
  if (!currentPromptSnapshot) return;
  const sec = currentPromptSnapshot.sections.find(s => s.id === sectionId);
  if (!sec) return;
  navigator.clipboard.writeText(sec.content).then(() => {
    if (btnEl) {
      const orig = btnEl.innerHTML;
      btnEl.innerHTML = "<span>✓</span> Copied!";
      btnEl.style.color = "var(--accent-green)";
      setTimeout(() => {
        btnEl.innerHTML = orig;
        btnEl.style.color = "";
      }, 1500);
    }
  }).catch(err => {
    console.error("Clipboard copy failed:", err);
  });
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

