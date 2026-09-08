"""MCP server — Model Context Protocol (JSON-RPC 2.0) sur POST /mcp."""
from api_gateway.mcp_server.permissions import (
    TOOL_SCOPES,
    list_tools,
    resource_allowed,
    tool_allowed,
)
from api_gateway.mcp_server.server import router

__all__ = ["router", "TOOL_SCOPES", "list_tools", "tool_allowed", "resource_allowed"]
