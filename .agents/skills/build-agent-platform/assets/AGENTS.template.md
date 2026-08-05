# Generated Agent Platform Instructions

## Ownership Boundaries

- The Agent Server owns the pi Runtime Adapter, Agent/Tool/Skill registries,
  Session application service, HTTP/SSE handlers, and delegation.
- Internal modules keep pi integration, Tool execution, Skill discovery, and
  Session persistence replaceable without requiring separate packages.
- The InsForge adapter owns external Auth, database, and Storage wire
  contracts.
- `web-bff` owns browser authentication, opaque browser Sessions, and proxying to Agent Server.
- `mcp` owns optional MCP client or server integration.
- `migrations`, `nginx`, Compose files, and deployment scripts own infrastructure configuration.

Do not place business concepts, prompts, product schemas, or business data ownership in shared platform modules.

## Root Commands

Replace these examples with the target repository's actual commands:

```sh
npm run build
npm test
npm run check
```

Document commands for local development, profile startup, integration checks,
and end-to-end verification. Keep one root verification command when the
repository supports it.
