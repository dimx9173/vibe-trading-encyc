# Architecture choices

Use this reference while designing the platform. Treat the boundaries as
guidance; select concrete packages and protocols from the target repository.

## Profiles

- **Core**: pi adapter, Agent/Tool/Skill registries, delegation, Sessions,
  Agent Server, and optionally a CLI. It starts without external
  infrastructure.
- **Production**: Core plus external backend adapters, durable Sessions, an
  authenticated browser BFF, observability, and deployment configuration.
- **MCP**: an optional extension that imports remote Tools through the same
  Tool Registry.

Profiles are composition roots, not duplicated implementations.

## Runtime boundaries

```text
client -> BFF (when browser auth is needed) -> Agent Server
                                             |-> pi runtime
                                             |-> Tool Registry
                                             |-> Skill Registry
                                             |-> Session Repository
                                             `-> optional backend/MCP adapters
```

The Agent Server is the composition root. Keep pi-specific messages and
callbacks behind a Runtime Adapter so registries, Sessions, HTTP handlers, and
tests can use platform-owned types.

## Decisions to make explicitly

Record:

- Agents, prompts, models, Tool grants, and delegation targets;
- local filesystem trust boundary for `read`, `write`, `edit`, and `bash`;
- Skill roots and precedence;
- Session lifetime and restart requirements;
- HTTP, SSE, CLI, browser, and MCP interfaces;
- external backend ownership and identity propagation;
- deployment topology and public/private routes;
- acceptance tests and non-goals.

Avoid adding queues, distributed locks, event sourcing, multi-region
coordination, Kubernetes, or a policy engine unless current requirements need
them.
