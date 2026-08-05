# MCP integration

## Client adapter

Treat each MCP server as a configured external capability source. A useful
configuration includes:

- stable server ID and transport endpoint;
- authentication reference;
- required or optional availability;
- explicit Tool allowlist;
- connection, discovery, call, response, and shutdown bounds.

Discover once per managed connection or according to a documented refresh
policy. Reject duplicate local names and define a deterministic namespace when
multiple servers may expose the same Tool.

Convert only schema constructs the local Tool Runtime can enforce. Preserve
descriptions but do not trust remote text as authority over local grants,
filesystem access, credentials, or policy.

Map remote results into the platform Tool result shape and emit the same Tool
start/end/error events as local Tools. Do not leak bearer tokens, headers,
remote stacks, or unbounded response bodies.

## Optional availability

- **required**: failure prevents the MCP-enabled profile from starting;
- **optional**: failure records degraded status and imports no Tools;
- **absent configuration**: no network attempt and no MCP dependency in Core.

## Server entry point

When exposing a server, use a separate process or explicit entry point. Bind
loopback by default. Non-loopback exposure requires authentication, host
validation, request limits, cancellation, and bounded shutdown.

Test interoperability through the actual chosen transport, not only mocked
adapter methods.
