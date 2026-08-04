# Deployment decisions

## Before templating

Confirm:

- public origin and TLS termination;
- public routes and private service ports;
- BFF-to-Agent-Server URL;
- external InsForge and model API egress;
- migration command;
- health/readiness contracts;
- graceful shutdown budget;
- secret injection and rotation;
- optional MCP exposure;
- rollback unit: image, migration, and configuration.

## Routing

For a browser product, route login, logout, health, API, and SSE through the
BFF. Keep the Agent Server private. Disable nginx buffering for SSE and set
timeouts longer than the bounded Agent turn.

If MCP is public, give it an explicit route and authentication boundary.
Do not accidentally expose external InsForge through the application edge.

## Compose

Only the edge normally publishes a host port. Use a private network for
application traffic and allow egress only where required. Give long-running
services health checks and stop grace periods. Keep migration one-shot and
optional profiles explicit.

## Operations

Document commands for build, migrate, start, health, smoke, logs, upgrade, and
rollback. A rollback plan must account for forward-only database changes.
Never commit production credentials or record them in verification evidence.
