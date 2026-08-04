---
name: add-mcp-profile
description: Add optional Model Context Protocol support to an Agent platform. Use when importing MCP server Tools through the platform Tool Registry, configuring required or optional MCP connections, or exposing a small MCP server from the project.
---

# Add MCP Profile

Add MCP as an optional composition profile after the Core Tool Registry works.
Read [MCP integration](references/mcp-integration.md) before implementation.

## Workflow

1. Inspect the current official MCP SDK API and the target server transport.
2. Confirm server IDs, endpoints, authentication source, Tool allowlists,
   required versus optional availability, schemas, timeouts, response limits,
   and shutdown expectations.
3. Implement an adapter that discovers allowlisted remote Tools and registers
   them through the existing Tool Registry.
4. Keep Agent Tool grants authoritative. Discovery never grants an imported
   Tool to an Agent.
5. Normalize remote schemas into the platform's schema representation. Reject
   unsupported schemas instead of silently making them unrestricted.
6. Propagate cancellation and bound connection, discovery, invocation,
   response, and close operations.
7. If the project exposes an MCP server, keep it a separate entry point and
   register only intentional Tools.
8. Test a real local transport path plus unavailable, timeout, cancellation,
   name-conflict, schema, output-limit, and shutdown behavior.
9. Confirm Core and Production start normally with MCP configuration absent.

Required-server failure stops only the MCP-enabled composition root. Optional
failure reports a degraded state and registers no phantom Tools.

Do not copy a fixed SDK version or server implementation from this Skill Pack.
Pin versions in the target project after checking current compatibility.
