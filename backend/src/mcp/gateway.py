# SPDX-License-Identifier: FSL-1.1-ALv2
"""MCP Gateway orchestrator — composes auth, routing, cache, policy, upstream."""

from __future__ import annotations

import json
from typing import Any

from ..core.errors import ProblemException
from .auth import OidcTokenVerifier
from .cache import TtlToolCache
from .policy import OpaGatewayPolicy
from .registry import McpServerRegistry, ServerDescriptor
from .routing import HeaderRouter
from .upstream import McpUpstream


class McpGateway:
    """Stateless MCP gateway orchestrator."""

    def __init__(
        self,
        *,
        registry: McpServerRegistry,
        verifier: OidcTokenVerifier,
        router: HeaderRouter,
        policy: OpaGatewayPolicy,
        cache: TtlToolCache,
        upstream: McpUpstream,
        agent_blast_radius: str = "read_only",
    ) -> None:
        self._registry = registry
        self._verifier = verifier
        self._router = router
        self._policy = policy
        self._cache = cache
        self._upstream = upstream
        self._agent_blast_radius = agent_blast_radius

    async def handle_tools_list(self, *, authorization: str | None, headers: dict[str, str]) -> dict[str, Any]:
        """tools/list: authenticate → route → cache/upstream → OPA filter → return."""
        claims = await self._verifier.verify(authorization)
        route = self._router.route(headers)

        # Cache or upstream
        tools = await self._cache.get(route.server.name)
        ttl_ms = None
        if tools is None:
            upstream_result = await self._upstream.list_tools(route.server)
            tools = upstream_result.get("tools", [])
            ttl_ms = upstream_result.get("ttl_ms")
            await self._cache.put(route.server.name, tools, ttl_ms)

        # OPA filter on EVERY response (including cache hits)
        allowed = await self._policy.filter_tools(
            server=route.server.name,
            tools=tools,
            claims=claims,
            blast_radius=self._agent_blast_radius,
        )

        return {"tools": allowed}

    async def handle_tools_call(
        self, *, authorization: str | None, headers: dict[str, str], body: bytes
    ) -> dict[str, Any]:
        """tools/call: authenticate → route → parse tool → resolve metadata → OPA authorize → invoke."""
        claims = await self._verifier.verify(authorization)
        route = self._router.route(headers)  # body-independent

        # Parse called tool AFTER route is fixed
        call = self._parse_tools_call(body)

        # Resolve metadata locally (no upstream I/O)
        metadata = self._resolve_metadata(route.server, call["tool"])

        # OPA authorize (deny = return before dispatch)
        await self._policy.authorise_call(
            server=route.server.name,
            tool=call["tool"],
            metadata=metadata,
            claims=claims,
            blast_radius=self._agent_blast_radius,
        )

        # ONLY on allow: invoke upstream
        return await self._upstream.call_tool(route.server, call)

    def _parse_tools_call(self, body: bytes) -> dict[str, Any]:
        """Parse a tools/call JSON-RPC body into {tool, arguments}.

        Raises 400 on malformed body.
        """
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ProblemException(
                status=400,
                type_suffix="mcp-invalid-body",
                title="Invalid request body",
                detail="Request body is not valid JSON.",
            ) from e

        if not isinstance(payload, dict):
            raise ProblemException(
                status=400,
                type_suffix="mcp-invalid-body",
                title="Invalid request body",
                detail="Request body must be a JSON object.",
            )

        params = payload.get("params", {})
        tool_name = params.get("name")
        if not tool_name or not isinstance(tool_name, str):
            raise ProblemException(
                status=400,
                type_suffix="mcp-missing-tool-name",
                title="Missing tool name",
                detail="params.name is required in tools/call.",
            )

        return {
            "tool": tool_name,
            "arguments": params.get("arguments", {}),
        }

    def _resolve_metadata(self, server: ServerDescriptor, tool_name: str) -> dict[str, Any]:
        """Resolve tool metadata from the registry (local, no I/O).

        Returns metadata dict. Raises 404 if tool metadata cannot be resolved.
        """
        # Check that the server has capabilities for tool calls
        if "tools/call" not in server.capabilities:
            raise ProblemException(
                status=404,
                type_suffix="mcp-tool-not-found",
                title="Tool not found",
                detail=f"Server '{server.name}' does not support tools/call.",
            )

        return {
            "server": server.name,
            "tool": tool_name,
            "server_url": server.url,
        }

    async def aclose(self) -> None:
        """Clean up resources."""
        pass
