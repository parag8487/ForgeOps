# SPDX-License-Identifier: FSL-1.1-ALv2
"""OPA gateway policy enforcement (Design §12.3).

Fail-closed: OPA unavailable → empty tool list; denied call → 403.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.errors import ProblemException

logger = logging.getLogger(__name__)


class OpaGatewayPolicy:
    """Policy enforcement via Open Policy Agent.

    - filter_tools is fail-closed: OPA unavailable → empty list.
    - authorise_call raises 403 on deny.
    """

    def __init__(
        self,
        *,
        opa_url: str = "http://localhost:8181",
        filter_path: str = "/v1/data/forgeops/mcp/filter_tools",
        authz_path: str = "/v1/data/forgeops/mcp/allow_call",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._opa_url = opa_url.rstrip("/")
        self._filter_path = filter_path
        self._authz_path = authz_path
        self._http = http or httpx.AsyncClient(timeout=5.0)

    async def filter_tools(
        self,
        tools: list[dict[str, Any]],
        *,
        subject: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter tools via OPA. Returns empty list if OPA is unavailable (fail-closed)."""
        payload = {
            "input": {
                "tools": tools,
                "subject": subject,
                "context": context or {},
            }
        }
        try:
            resp = await self._http.post(
                f"{self._opa_url}{self._filter_path}",
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            # OPA returns {"result": [...allowed tools...]}
            return result.get("result", [])
        except Exception:
            logger.warning("OPA unavailable for filter_tools, fail-closed → empty list")
            return []

    async def authorise_call(
        self,
        *,
        tool_name: str,
        subject: str,
        arguments: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Authorise a tool call via OPA. Raises 403 on deny or OPA failure."""
        payload = {
            "input": {
                "tool_name": tool_name,
                "subject": subject,
                "arguments": arguments or {},
                "context": context or {},
            }
        }
        try:
            resp = await self._http.post(
                f"{self._opa_url}{self._authz_path}",
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            allowed = result.get("result", False)
        except Exception:
            logger.warning("OPA unavailable for authorise_call, fail-closed → deny")
            allowed = False

        if not allowed:
            raise ProblemException(
                status=403,
                type_suffix="mcp-call-denied",
                title="Tool call denied",
                detail=f"Policy denied call to tool '{tool_name}' for subject '{subject}'.",
            )
