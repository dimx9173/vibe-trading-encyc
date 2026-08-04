---
name: build-agent-platform
description: Design and build a pi-based TypeScript Agent platform. Use when creating or restructuring an Agent runtime with Agent, Tool, and Skill registries; supervisor delegation; sessions; an HTTP/SSE server; or a CLI. Route external InsForge, MCP, deployment, and final verification to their dedicated Skills.
---

# Build Agent Platform

Build the platform in the user's repository. Adapt the architecture to existing
code instead of copying a fixed framework.

Read only the references needed for the current phase:

- [Architecture choices](references/architecture.md) for boundaries and profiles.
- [Core runtime](references/core-runtime.md) while implementing pi, registries,
  delegation, Skills, Sessions, server, and CLI.
- [Implementation workflow](references/implementation-workflow.md) for staging
  and acceptance evidence.

Use files in `assets/` as small starting points, never as an imposed workspace
layout. Inspect current pi package APIs before implementing an adapter.

## Workflow

1. Inspect repository instructions, packages, tests, deployment files, and
   existing runtime boundaries.
2. Confirm the intended Agents, model policy, Tool grants, Skill roots,
   Session durability, interfaces, optional profiles, and non-goals.
3. Propose the project-specific architecture, package boundaries, request
   flows, implementation sequence, and acceptance checks. Obtain user approval
   before a broad implementation.
4. Implement the smallest useful Core vertically:
   - pi Runtime Adapter;
   - Agent Registry;
   - Tool Registry with `read`, `write`, `edit`, `bash`, and `web_search`;
   - `delegate_to_agent`;
   - Skill discovery and progressive loading;
   - Session abstraction;
   - Agent Server and optional CLI.
5. Add tests at public boundaries. Prefer behavior tests over tests that freeze
   filenames, prose, private helper counts, or one exact implementation.
6. Invoke `$integrate-insforge` when an external InsForge-backed Production
   profile is requested.
7. Invoke `$add-mcp-profile` when MCP is requested.
8. Invoke `$deploy-agent-platform` when deployment assets are requested.
9. Finish with `$verify-agent-platform`.

## Stable decisions

- Keep Agent core code TypeScript. Infrastructure files use their native
  formats.
- Define one `AgentDefinition`. An Agent is a Supervisor only when granted
  `delegate_to_agent`; otherwise it is a Subagent.
- Register Tools centrally and grant them explicitly per Agent.
- Discover Skills from configured roots such as `.codex/skills` and
  `.agents/skills`. Support ordinary Skill directories and their referenced
  files, scripts, and assets; do not assume every Skill is a single file.
- Keep Skills from expanding Tool grants.
- Keep Core independent of InsForge, BFF, nginx, and MCP.
- Put business Agents, prompts, data schemas, and model choices in the target
  project.

## Adaptation rules

- Preserve an existing monorepo or package manager unless change is necessary.
- Pin versions in the generated project only after checking current compatible
  releases and APIs.
- Choose in-memory or durable Sessions based on requirements; do not introduce
  leases, fencing, recovery jobs, or an event ledger without a demonstrated
  concurrency or restart need.
- Choose HTTP routes, ports, schemas, and repository methods from the target
  product. The references describe responsibilities, not mandatory names.
- Stop when an external contract or consequential product decision is unknown.
