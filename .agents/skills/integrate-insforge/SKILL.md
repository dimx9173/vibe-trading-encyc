---
name: integrate-insforge
description: Connect an Agent platform to a user-provided InsForge backend. Use when adding InsForge Auth, PostgREST/database access, Storage, durable Sessions, or a browser BFF without vendoring or provisioning InsForge itself.
---

# Integrate InsForge

Connect the target platform to an external InsForge deployment. Do not include
InsForge itself in the generated repository or Compose stack.

Read:

- [InsForge boundary](references/insforge-boundary.md) for Auth, database, and
  Storage adapters.
- [Sessions and BFF](references/sessions-and-bff.md) only when durable
  conversations or browser access are in scope.

## Workflow

1. Inspect the actual InsForge deployment contract: base URL, Auth endpoints,
   response shapes, token rotation, PostgREST profile, Storage API, RLS, and
   health endpoint. Do not guess from another deployment.
2. Define TypeScript ports owned by the Agent platform. Keep InsForge wire
   types inside adapters.
3. Propagate the authenticated user's identity for user-owned operations.
   Introduce a separate trusted-worker context only for explicitly
   system-owned work.
4. Implement injected, request-scoped Auth, database, and Storage clients with
   cancellation, timeouts, response limits, and normalized errors.
5. Add durable Session persistence only to the level required by the product.
   Preserve exact messages and Agent state when restart continuity is
   required; add leases or recovery only when concurrent turns or interrupted
   work make them necessary.
6. When a browser UI is in scope, add a BFF that stores provider tokens
   server-side, issues an opaque cookie, overwrites caller-supplied identity,
   and proxies only an explicit route allowlist to the Agent Server.
7. Test with fake HTTP/database boundaries first. Run live checks only when the
   user provides an authorized environment.

## Required boundaries

- InsForge remains external and configurable.
- Browser credentials never reach the Agent Server from browser-controlled
  headers.
- User operations never fall back to a system credential.
- RLS and Storage authorization remain backend responsibilities.
- Tokens do not live in module-global mutable state or browser-readable
  storage.
- The BFF does not become a second Agent runtime or business-logic layer.
- Application tables, buckets, schemas, and retention rules belong to the
  target project.

Stop for a contract decision when endpoints, identity ownership, RLS policy,
token semantics, or Session recovery expectations are unknown.
