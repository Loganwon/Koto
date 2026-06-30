# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
MCP (Model Context Protocol) Adapter
======================================
将 Anthropic 开源的 Model Context Protocol 标准接入 Koto 工具系统。

MCP 是 2024 年底由 Anthropic 发布的开放标准协议（MIT 许可），
目前已有 300+ 服务提供 MCP server（文件系统、数据库、GitHub、Slack、
Figma、Notion、Puppeteer 等）。

协议规范：https://modelcontextprotocol.io/specification
官方 Python SDK：pip install mcp

本模块实现：
  1. MCPServerProcess  — 通过 stdio 启动/通信 MCP server 子进程
  2. MCPHTTPClient     — 通过 HTTP/SSE 连接远程 MCP server
  3. MCPToolAdapter    — 将 MCP tools 转化为 Koto ToolRegistry 可用格式
  4. MCPRegistry       — 管理多个 MCP server 的连接池

架构（仿照 Anthropic Claude Desktop 的 MCP 集成方式，原创实现）：

  ┌────────────────────────────────────┐
  │         Koto UnifiedAgent          │
  │  (ToolRegistry + MCPToolAdapter)   │
  └───────────────┬────────────────────┘
                  │ JSON-RPC 2.0
       ┌──────────┴──────────┐
       │                     │
  [stdio MCP]          [HTTP/SSE MCP]
  ./node_modules/      http://localhost:
  @modelcontextprotocol/                8080
  server-filesystem

用法
----
    from app.core.agent.mcp_adapter import MCPRegistry

    registry = MCPRegistry()

    # 注册 stdio MCP server（Node.js 文件系统服务器）
    registry.add_stdio_server(
        name="filesystem",
        command=["npx", "@modelcontextprotocol/server-filesystem", "/tmp"],
    )

    # 注册 HTTP MCP server
    registry.add_http_server(
        name="github",
        url="http://localhost:8080",
    )

    # 连接并加载工具列表
    await registry.connect_all()

    # 将所有 MCP 工具注入 Koto ToolRegistry
    from app.core.agent.tool_registry import ToolRegistry
    tool_registry = ToolRegistry()
    registry.inject_into(tool_registry)

    # 同步使用
    with MCPRegistry.sync() as sync_reg:
        sync_reg.add_stdio_server("filesystem", ["npx", "..."])
        sync_reg.connect_sync("filesystem")
        result = sync_reg.call_tool_sync("filesystem", "read_file", {"path": "/tmp/test.txt"})
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── MCP Python SDK（可选依赖） ────────────────────────────────────────────────
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _MCP_SDK_AVAILABLE = True
except ImportError:
    _MCP_SDK_AVAILABLE = False
    logger.debug("[MCPAdapter] mcp SDK 未安装，将使用内置 JSON-RPC 实现")

# ── httpx（HTTP MCP server 用） ───────────────────────────────────────────────
try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0 工具函数（内置实现，不依赖 SDK）
# ─────────────────────────────────────────────────────────────────────────────


def _make_request(method: str, params: Any = None, req_id: int = 1) -> bytes:
    obj: Dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        obj["params"] = params
    return (json.dumps(obj) + "\n").encode()


def _parse_response(line: bytes) -> Dict:
    return json.loads(line.decode().strip())


# ─────────────────────────────────────────────────────────────────────────────
# MCPStdioClient — 内置 stdio 实现（无需 mcp SDK）
# ─────────────────────────────────────────────────────────────────────────────


class MCPStdioClient:
    """
    通过 stdin/stdout 与 MCP server 子进程通信。
    实现 MCP 协议的 initialize / tools/list / tools/call 三个方法。
    """

    def __init__(
        self,
        command: List[str],
        timeout: int = 10,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ):
        self.command = command
        self.timeout = timeout
        self.env = env or {}
        self.cwd = cwd
        self._proc: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._tools: List[Dict] = []
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """启动子进程并完成 MCP 握手（initialize）。"""
        try:
            proc_env = os.environ.copy()
            proc_env.update({str(k): str(v) for k, v in self.env.items()})
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                cwd=self.cwd or None,
            )
            # MCP initialize 握手
            resp = self._rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "koto", "version": "1.0.0"},
                },
            )
            if "error" in resp:
                logger.error(f"[MCPStdio] 初始化失败: {resp['error']}")
                return False
            # initialized notification
            self._notify("notifications/initialized")
            return True
        except Exception as e:
            logger.error(f"[MCPStdio] 连接失败 {self.command}: {e}")
            return False

    def list_tools(self) -> List[Dict]:
        """获取 server 提供的工具列表。"""
        resp = self._rpc("tools/list")
        tools = resp.get("result", {}).get("tools", [])
        self._tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        """调用指定工具，返回内容列表（MCP 规范格式）。"""
        resp = self._rpc(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        if "error" in resp:
            raise RuntimeError(f"MCP tool error: {resp['error']}")
        content = resp.get("result", {}).get("content", [])
        # 合并文本内容
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else str(content)

    def disconnect(self):
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
            self._proc = None

    # ── 内部 RPC ──────────────────────────────────────────────────────────────

    def _rpc(self, method: str, params: Any = None) -> Dict:
        with self._lock:
            if not self._proc or not self._proc.stdin or not self._proc.stdout:
                return {"error": "MCP process is not running"}
            if self._proc.poll() is not None:
                return {
                    "error": f"MCP process exited with code {self._proc.returncode}"
                }
            self._req_id += 1
            req_id = self._req_id
            req = _make_request(method, params, req_id)
            self._proc.stdin.write(req)
            self._proc.stdin.flush()
            # 读取响应行
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                line = self._proc.stdout.readline()
                if line:
                    try:
                        resp = _parse_response(line)
                        if resp.get("id") == req_id or "error" in resp:
                            return resp
                    except json.JSONDecodeError:
                        continue
            return {"error": "timeout"}

    def _notify(self, method: str, params: Any = None):
        """发送无需响应的通知。"""
        obj = {"jsonrpc": "2.0", "method": method}
        if params:
            obj["params"] = params
        self._proc.stdin.write((json.dumps(obj) + "\n").encode())
        self._proc.stdin.flush()


# ─────────────────────────────────────────────────────────────────────────────
# MCPHTTPClient — HTTP/SSE MCP server 客户端
# ─────────────────────────────────────────────────────────────────────────────


class MCPHTTPClient:
    """
    通过 HTTP POST 调用 MCP server（适用于支持 Streamable HTTP 的 MCP servers）。
    """

    def __init__(self, base_url: str, api_key: str = "", timeout: int = 30):
        if not _HTTPX_AVAILABLE:
            raise ImportError("httpx required: pip install httpx")
        self.base_url = base_url.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.timeout = timeout
        self._req_id = 0

    def list_tools(self) -> List[Dict]:
        resp = self._post("tools/list")
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        resp = self._post(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        if "error" in resp:
            raise RuntimeError(f"MCP HTTP error: {resp['error']}")
        content = resp.get("result", {}).get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else str(content)

    def _post(self, method: str, params: Any = None) -> Dict:
        self._req_id += 1
        payload = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params:
            payload["params"] = params
        try:
            import httpx

            r = httpx.post(
                f"{self.base_url}/mcp",
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"[MCPHTTPClient] 调用失败 {method}: {e}")
            return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# MCPServerEntry — 描述一个已注册的 MCP server
# ─────────────────────────────────────────────────────────────────────────────


class MCPServerEntry:
    def __init__(self, name: str, client, server_type: str):
        self.name = name
        self.client = client  # MCPStdioClient | MCPHTTPClient
        self.server_type = server_type  # "stdio" | "http"
        self.tools: List[Dict] = []
        self.connected = False
        self.last_error = ""

    def connect(self) -> bool:
        try:
            if self.server_type == "stdio":
                ok = self.client.connect()
            else:
                ok = True  # HTTP 无需握手
            if ok:
                self.tools = self.client.list_tools()
                self.connected = True
                self.last_error = ""
                logger.info(
                    f"[MCPAdapter] [{self.name}] 已连接，{len(self.tools)} 个工具: "
                    f"{[t['name'] for t in self.tools]}"
                )
            else:
                self.last_error = "connect failed"
            return ok
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            logger.warning(f"[MCPAdapter] [{self.name}] 连接失败: {exc}")
            return False

    def disconnect(self):
        if self.server_type == "stdio":
            self.client.disconnect()
        self.connected = False


# ─────────────────────────────────────────────────────────────────────────────
# MCPRegistry — 管理多个 MCP server
# ─────────────────────────────────────────────────────────────────────────────


class MCPRegistry:
    """
    管理多个 MCP server 连接，并将其工具注入 Koto ToolRegistry。

    示例配置（等价于 Claude Desktop 的 mcpServers 配置）：
    {
      "filesystem": {
        "type": "stdio",
        "command": ["npx", "@modelcontextprotocol/server-filesystem", "/tmp"]
      },
      "github": {
        "type": "http",
        "url": "http://localhost:8080",
        "api_key": "..."
      }
    }
    """

    def __init__(self):
        self._servers: Dict[str, MCPServerEntry] = {}

    def add_stdio_server(
        self,
        name: str,
        command: List[str],
        timeout: int = 10,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> "MCPRegistry":
        """注册一个 stdio MCP server（本地子进程）。"""
        client = MCPStdioClient(command=command, timeout=timeout, env=env, cwd=cwd)
        self._servers[name] = MCPServerEntry(name, client, "stdio")
        return self

    def add_http_server(
        self,
        name: str,
        url: str,
        api_key: str = "",
        timeout: int = 30,
    ) -> "MCPRegistry":
        """注册一个 HTTP MCP server（远程或本地）。"""
        client = MCPHTTPClient(base_url=url, api_key=api_key, timeout=timeout)
        self._servers[name] = MCPServerEntry(name, client, "http")
        return self

    def from_config(self, config: Dict) -> "MCPRegistry":
        """
        从配置 dict 批量注册 server（兼容 Claude Desktop 配置格式）。

        config 格式：
          {
            "server_name": {
              "type": "stdio"|"http",
              "command": "node",  # stdio 时；也兼容 ["node", "server.js"]
              "args": ["server.js"],
              "env": {"TOKEN": "..."},
              "cwd": "C:/project",
              "url": "...",       # http 时
              "api_key": "...",   # http 可选
            }
          }
        """
        for name, cfg in config.items():
            stype = cfg.get("type", "stdio")
            if stype == "stdio":
                command = cfg["command"]
                if isinstance(command, str):
                    command = [command]
                args = cfg.get("args") or []
                if isinstance(args, str):
                    args = [args]
                self.add_stdio_server(
                    name,
                    [*command, *args],
                    timeout=int(cfg.get("timeout", 10)),
                    env=cfg.get("env") or {},
                    cwd=cfg.get("cwd"),
                )
            elif stype == "http":
                self.add_http_server(
                    name,
                    cfg["url"],
                    api_key=cfg.get("api_key", ""),
                    timeout=int(cfg.get("timeout", 30)),
                )
        return self

    def connect_all(self) -> Dict[str, bool]:
        """连接所有注册的 server，返回 {name: success} 字典。"""
        results = {}
        for name, entry in self._servers.items():
            if not entry.connected:
                results[name] = entry.connect()
        return results

    def connect(self, server_name: str) -> bool:
        """连接单个 server。"""
        entry = self._servers.get(server_name)
        if not entry:
            raise KeyError(f"MCP server '{server_name}' not registered")
        return entry.connect()

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict) -> Any:
        """调用指定 server 的指定工具。"""
        entry = self._servers.get(server_name)
        if not entry:
            raise KeyError(f"MCP server '{server_name}' not registered")
        if not entry.connected:
            raise RuntimeError(f"MCP server '{server_name}' not connected")
        return entry.client.call_tool(tool_name, arguments)

    def list_all_tools(self) -> List[Dict]:
        """返回所有 server 的工具列表，附加 server 来源信息。"""
        tools = []
        for name, entry in self._servers.items():
            if entry.connected:
                for t in entry.tools:
                    tools.append({**t, "_mcp_server": name})
        return tools

    def status(self) -> Dict[str, Any]:
        """返回当前 MCP server 连接状态，供 API / 诊断入口使用。"""
        servers = {}
        total_tools = 0
        for name, entry in self._servers.items():
            tool_names = [t.get("name", "") for t in entry.tools]
            total_tools += len(tool_names)
            servers[name] = {
                "type": entry.server_type,
                "connected": entry.connected,
                "tool_count": len(tool_names),
                "tools": tool_names,
                "last_error": entry.last_error,
            }
        return {
            "server_count": len(servers),
            "tool_count": total_tools,
            "servers": servers,
        }

    def inject_into(self, tool_registry) -> int:
        """
        将所有 MCP server 的工具注入 Koto ToolRegistry。

        工具名称会被命名空间化为 "mcp__{server_name}__{tool_name}"
        以避免与 Koto 原生工具冲突。

        返回注入的工具数量。
        """
        count = 0
        for server_name, entry in self._servers.items():
            if not entry.connected:
                continue
            for tool_def in entry.tools:
                original_name = tool_def["name"]
                koto_name = f"mcp__{server_name}__{original_name}"
                description = f"[MCP:{server_name}] {tool_def.get('description', '')}"

                # 构造闭包，捕获 server_name / original_name
                def _make_caller(sn: str, tn: str):
                    def _call(**kwargs):
                        return self.call_tool(sn, tn, kwargs)

                    _call.__doc__ = description
                    return _call

                caller = _make_caller(server_name, original_name)

                # 将 MCP JSON Schema 转为 Koto parameters 格式
                parameters = tool_def.get("inputSchema", {})

                tool_registry.register_tool(
                    name=koto_name,
                    func=caller,
                    description=description,
                    parameters=parameters,
                )
                count += 1
        if count:
            logger.info(f"[MCPAdapter] 已将 {count} 个 MCP 工具注入 ToolRegistry")
        return count

    def disconnect_all(self):
        for entry in self._servers.values():
            entry.disconnect()

    def __enter__(self):
        self.connect_all()
        return self

    def __exit__(self, *args):
        self.disconnect_all()

    # ── 从 config/user_settings.json 加载 MCP 配置 ────────────────────────────

    @classmethod
    def from_koto_settings(cls) -> "MCPRegistry":
        """
        从 Koto 的 config/user_settings.json 读取 mcp_servers 配置段。

        user_settings.json 中增加如下字段即可：
        {
          "mcp_servers": {
            "filesystem": {
              "type": "stdio",
              "command": ["npx", "@modelcontextprotocol/server-filesystem", "C:/Users/me/Documents"]
            }
          }
        }
        """
        import pathlib

        settings_path = (
            pathlib.Path(__file__).parents[3] / "config" / "user_settings.json"
        )
        reg = cls()
        try:
            if settings_path.exists():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                mcp_cfg = data.get("mcp_servers") or data.get("mcpServers") or {}
                if mcp_cfg:
                    reg.from_config(mcp_cfg)
                    logger.info(
                        f"[MCPAdapter] 从 user_settings.json 加载了 "
                        f"{len(mcp_cfg)} 个 MCP server 配置"
                    )
        except Exception as e:
            logger.warning(f"[MCPAdapter] 加载 MCP 配置失败: {e}")
        return reg
