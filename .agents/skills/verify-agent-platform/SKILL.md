---
name: verify-agent-platform
description: Verify an Agent platform and produce evidence for its approved capabilities. Use after building or changing Core, InsForge, MCP, BFF, Session, or deployment behavior, especially before declaring the platform complete.
---

# Verify Agent Platform

Read [Verification matrix](references/verification-matrix.md). Copy the report
template only when the project does not already have an evidence format.

## Workflow

1. Reconstruct the approved capabilities and non-goals from the target
   project's design. Do not use pi-platform-skills's own architecture as the catalog.
2. Run cheap hermetic checks first: format or lint when configured, typecheck,
   unit tests, contract tests, and build.
3. Run applicable integration checks for pi, Tools, Skills, Sessions,
   InsForge, BFF, SSE, MCP, and deployment.
4. Exercise the platform through its public entry point. Include restart,
   cancellation, disconnect, or concurrency cases only when the product claims
   those behaviors.
5. Record the exact command, expected result, observed result, and status for
   each capability. Unavailable, skipped, inferred, and manually assumed
   results are not PASS.
6. Run `scripts/audit-report.mjs <report.md>` to catch incomplete rows.
7. Report failures and residual risks without converting them into success.

The auditor validates report structure only. It never executes commands and
cannot establish that an observation is true.

Keep credentials, cookies, tokens, private endpoints, and user data out of
evidence.
