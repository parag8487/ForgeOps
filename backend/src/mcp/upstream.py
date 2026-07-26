# SPDX-License-Identifier: FSL-1.1-ALv2
"""Upstream MCP server transport with trace propagation (Design §12.3).

Forwards requests to target MCP servers, propagating W3C Trace Context headers.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.errors import ProblemException

logger = logging.getLogger(__name__)

# W3C Trace Context headers to propagate
_TRACE_HEADERS = ("traceparent", "tracestate")


class McpUpstream:
    """Forwards MCP requests to upstream servers with trace propagation."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def list_tools(
        self,
        server_url: str,
        *,
        trace_headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Forward a tools/list request to the upstream MCP server."""
        headers = self._build_headers(trace_headers)
        headers["Content-Type"] = "application/json"

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        }

        try:
            resp = await self._http.post(
                f"{server_url.rstrip('/')}/mcp",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            body = resp.json()
            return body.get("result", {}).get("tools", [])
        except httpx.HTTPStatusError as exc:
            logger.error("upstream tools/list failed: %s", exc)
            raise ProblemException(
                status=502,
                type_suffix="mcp-upstream-error",
                title="Upstream MCP server error",
                detail=f"tools/list to {server_url} returned {exc.response.status_code}.",
            ) from exc
        except Exception as exc:
            logger.error("upstream tools/list transport error: %s", exc)
            raise ProblemException(
                status=502,
                type_suffix="mcp-upstream-unreachable",
                title="Upstream MCP server unreachable",
                detail=f"Could not reach upstream server at {server_url}.",
            ) from exc

    async def call_tool(
        self,
        server_url: str,
        *,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        trace_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Forward a tools/call request to the upstream MCP server."""
        headers = self._build_headers(trace_headers)
        headers["Content-Type"] = "application/json"

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }

        try:
            resp = await self._http.post(
                f"{server_url.rstrip('/')}/mcp",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            body = resp.json()
            return body.get("result", {})
        except httpx.HTTPStatusError as exc:
            logger.error("upstream tools/call failed: %s", exc)
            raise ProblemException(
                status=502,
                type_suffix="mcp-upstream-error",
                title="Upstream MCP server error",
                detail=f"tools/call '{tool_name}' to {server_url} returned {exc.response.status_code}.",
            ) from exc
        except Exception as exc:
            logger.error("upstream tools/call transport error: %s", exc)
            raise ProblemException(
                status=502,
                type_suffix="mcp-upstream-unreachable",
                title="Upstream MCP server unreachable",
                detail=f"Could not reach upstream server at {server_url}.",
            ) from exc

    def _build_headers(self, trace_headers: dict[str, str] | None) -> dict[str, str]:
        """Build request headers with trace propagation."""
        headers: dict[str, str] = {}
        if trace_headers:
            for h in _TRACE_HEADERS:
                if h in trace_headers:
                    headers[h] = trace_headers[h]
        return headers
