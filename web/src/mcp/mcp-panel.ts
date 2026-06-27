/**
 * MCP Host Panel - Koto coding agent entry point.
 * Shows connected agents, available tools, and MCP status.
 * Compiled into the main workspace bundle.
 */

interface MCPTool {
  name: string;
  description: string;
  inputSchema?: any;
}

interface MCPAgent {
  id: string;
  name: string;
  version: string;
  connectedAt: string;
  lastSeen?: string;
}

const MCP_STATE = {
  agents: [] as MCPAgent[],
  tools: [] as MCPTool[],
  ws: null as WebSocket | null,
  connected: false,
  connecting: false,
  serviceOnline: false,
  reqId: 0,
  pending: new Map<number, { resolve: Function; reject: Function }>(),
};

function _mcpLog(msg: string): void {
  console.log(`[MCP] ${msg}`);
}

async function _mcpConnect(): Promise<boolean> {
  if (MCP_STATE.connected || MCP_STATE.connecting) return MCP_STATE.connected;

  const host = location.hostname;
  const port = location.port || "5000";
  const url = `ws://${host}:${port}/ws/mcp`;

  return new Promise((resolve) => {
    MCP_STATE.connecting = true;
    MCP_STATE.ws = new WebSocket(url);

    MCP_STATE.ws.onopen = async () => {
      _mcpLog("Connected");
      try {
        // Initialize
        const initResp = await _mcpRPC("initialize", {
          protocolVersion: "2024-11-05",
          capabilities: { tools: {} },
          clientInfo: { name: "koto-ui", version: "2.0.0" },
        });
        _mcpLog(`Server: ${initResp.serverInfo?.name} v${initResp.serverInfo?.version}`);

        // List tools
        const toolsResp = await _mcpRPC("tools/list", {});
        MCP_STATE.tools = toolsResp.tools || [];
        _mcpLog(`Loaded ${MCP_STATE.tools.length} tools`);

        MCP_STATE.connected = true;
        MCP_STATE.connecting = false;
        _renderMCPPanel();
        resolve(true);
      } catch (e) {
        _mcpLog(`Init failed: ${e}`);
        MCP_STATE.connecting = false;
        resolve(false);
      }
    };

    MCP_STATE.ws.onclose = () => {
      _mcpLog("Disconnected");
      MCP_STATE.connected = false;
      MCP_STATE.connecting = false;
      MCP_STATE.ws = null;
      _renderMCPPanel();
    };

    MCP_STATE.ws.onerror = () => {
      MCP_STATE.connecting = false;
      resolve(false);
    };

    MCP_STATE.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        const pending = MCP_STATE.pending.get(msg.id);
        if (pending) {
          MCP_STATE.pending.delete(msg.id);
          if (msg.error) pending.reject(new Error(msg.error.message));
          else pending.resolve(msg.result);
        }
      } catch (_) { /* ignore parse errors */ }
    };
  });
}

function _mcpRPC(method: string, params: any): Promise<any> {
  return new Promise((resolve, reject) => {
    if (!MCP_STATE.ws || MCP_STATE.ws.readyState !== WebSocket.OPEN) {
      reject(new Error("Not connected"));
      return;
    }
    const id = ++MCP_STATE.reqId;
    MCP_STATE.pending.set(id, { resolve, reject });
    MCP_STATE.ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    // Timeout after 30s
    setTimeout(() => {
      if (MCP_STATE.pending.has(id)) {
        MCP_STATE.pending.delete(id);
        reject(new Error("Timeout"));
      }
    }, 30000);
  });
}

// ── UI Rendering ──

let _mcpPanelEl: HTMLElement | null = null;
let _mcpExpanded = false;

function _formatWsTime(value: unknown): string {
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  try {
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return "";
  }
}

async function _mcpRefreshRuntimeStatus(): Promise<void> {
  MCP_STATE.connecting = true;
  _renderMCPPanel();
  try {
    const [statusResp, toolsResp] = await Promise.all([
      fetch("/api/mcp/status", { headers: { Accept: "application/json" } }),
      fetch("/api/mcp/tools", { headers: { Accept: "application/json" } }),
    ]);
    const status = await statusResp.json();
    const tools = await toolsResp.json();
    if (!statusResp.ok || status.success !== true) throw new Error(status.error || `status ${statusResp.status}`);
    if (!toolsResp.ok || tools.success !== true) throw new Error(tools.error || `tools ${toolsResp.status}`);
    const sessions = Array.isArray(status.websocket?.external_sessions)
      ? status.websocket.external_sessions
      : [];
    MCP_STATE.serviceOnline = true;
    MCP_STATE.connected = true;
    MCP_STATE.tools = Array.isArray(tools.tools) ? tools.tools : [];
    MCP_STATE.agents = sessions.map((item: any) => ({
      id: String(item.id || ""),
      name: String(item.client_name || item.id || "unknown"),
      version: String(item.client_version || ""),
      connectedAt: _formatWsTime(item.connected_at),
      lastSeen: _formatWsTime(item.last_seen),
    }));
  } catch (error) {
    _mcpLog(`Status refresh failed: ${error}`);
    MCP_STATE.serviceOnline = false;
    MCP_STATE.connected = false;
    MCP_STATE.tools = [];
    MCP_STATE.agents = [];
  } finally {
    MCP_STATE.connecting = false;
    _renderMCPPanel();
    if (_mcpExpanded && _mcpPanelEl) {
      const detail = _mcpPanelEl.querySelector("#mcpDetailPanel") as HTMLElement;
      if (detail) detail.innerHTML = _renderMCPDetail();
    }
  }
}

function _renderMCPPanel(): void {
  if (!_mcpPanelEl) return;
  const dot = _mcpPanelEl.querySelector(".mcp-status-dot") as HTMLElement;
  const text = _mcpPanelEl.querySelector(".mcp-status-text") as HTMLElement;
  if (dot) dot.className = `mcp-status-dot ${MCP_STATE.serviceOnline ? "online" : MCP_STATE.connecting ? "connecting" : "offline"}`;
  if (text) text.textContent = MCP_STATE.serviceOnline
    ? `MCP: 服务可用 · ${MCP_STATE.tools.length} tools`
    : MCP_STATE.connecting ? "MCP: 检测中..." : "MCP: 不可用";
}

function _renderMCPDetail(): string {
  const tools = MCP_STATE.tools.map(t =>
    `<div class="mcp-tool-item"><strong>${_esc(t.name)}</strong><span class="mcp-tool-desc">${_esc(t.description || "")}</span></div>`
  ).join("");

  const agents = MCP_STATE.agents.length
    ? MCP_STATE.agents.map(a =>
        `<div class="mcp-agent-item">${_esc(a.name)}${a.version ? ` v${_esc(a.version)}` : ""} — ${_esc(a.lastSeen || a.connectedAt || "connected")}</div>`
      ).join("")
    : `<div class="mcp-empty">暂无外部 Agent 连接</div>`;

  return `
    <div class="mcp-detail-header">
      <strong>MCP Coding Agent Hub</strong>
      <button class="mcp-refresh-btn" onclick="window._mcpRefresh()">刷新</button>
    </div>
    <div class="mcp-section">
      <div class="mcp-section-title">可用工具 (${MCP_STATE.tools.length})</div>
      <div class="mcp-tool-list">${tools || '<div class="mcp-empty">加载中...</div>'}</div>
    </div>
    <div class="mcp-section">
      <div class="mcp-section-title">外部 Agent (${MCP_STATE.agents.length})</div>
      <div class="mcp-agent-list">${agents}</div>
    </div>
    <div class="mcp-section">
      <div class="mcp-section-title">外部接入方式</div>
      <pre class="mcp-code">python scripts/koto_mcp_cli.py --url ws://127.0.0.1:${location.port || "5000"}/ws/mcp</pre>
    </div>
  `;
}

function _esc(s: string): string {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Public API ──

function initMCPPanel(): HTMLElement {
  const el = document.createElement("div");
  el.className = "mcp-panel";
  el.innerHTML = `
    <div class="mcp-status-bar" id="mcpStatusBar" title="MCP Agent Hub">
      <span class="mcp-status-dot offline"></span>
      <span class="mcp-status-text">MCP: 离线</span>
      <svg class="mcp-expand-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
    </div>
    <div class="mcp-detail-panel" id="mcpDetailPanel" style="display:none"></div>
  `;

  _mcpPanelEl = el;
  const statusBar = el.querySelector("#mcpStatusBar") as HTMLElement;
  statusBar.addEventListener("click", () => {
    _mcpExpanded = !_mcpExpanded;
    const detail = el.querySelector("#mcpDetailPanel") as HTMLElement;
    if (_mcpExpanded) {
      detail.innerHTML = _renderMCPDetail();
      detail.style.display = "block";
    } else {
      detail.style.display = "none";
    }
    const arrow = el.querySelector(".mcp-expand-arrow") as HTMLElement;
    if (arrow) arrow.style.transform = _mcpExpanded ? "rotate(180deg)" : "";
  });

  _mcpRefreshRuntimeStatus();

  return el;
}

// Expose refresh globally
(window as any)._mcpRefresh = () => {
  _mcpRefreshRuntimeStatus();
  if (typeof (window as any).refreshMcpSettingsStatus === "function") {
    (window as any).refreshMcpSettingsStatus();
  }
};

// ── Expose to workspace ──
if (typeof window !== "undefined") {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.initMCPPanel = initMCPPanel;
  (window as any).WA._mcpRefresh = (window as any)._mcpRefresh;
}

export { initMCPPanel, MCP_STATE, _mcpConnect, _mcpRPC };
