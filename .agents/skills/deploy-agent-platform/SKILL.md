---
name: deploy-agent-platform
description: Prepare and validate deployment for an Agent platform. Use when adding nginx routing, Docker Compose, environment configuration, database migrations, health checks, or an authenticated smoke test for a single-host deployment.
---

# Deploy Agent Platform

Deploy only after the selected application profiles work locally. Read
[Deployment decisions](references/deployment.md), then adapt the templates to
the target project's real entry points and ports.

## Workflow

1. Map public routes and private upstreams. For a browser application, nginx
   should normally expose the BFF, not the Agent Server or InsForge.
2. Adapt `assets/compose.template.yml`, `assets/nginx.conf.template`, and
   `assets/.env.example`. Replace every placeholder; do not treat template
   names or ports as requirements.
3. Keep schema migration an explicit, idempotent command rather than an
   application-startup side effect.
4. Add health checks, bounded shutdown, log handling, and rollback steps.
5. Run `scripts/validate-nginx.sh <config>` after rendering nginx.
6. Adapt and run `scripts/smoke.sh` against the public origin. Add login,
   Session, chat, and SSE checks required by the target application.
7. Record build, migration, start, health, smoke, and rollback evidence without
   recording secrets.

## Defaults

- nginx is the only service with published host ports.
- Browser identity and authorization do not bypass the BFF.
- Agent Server, BFF, and optional MCP services use a private application
  network.
- External InsForge remains outside this Compose stack.
- Ordinary startup never mutates the database schema.
- Production uses HTTPS and secure cookies.
- MCP is deployed only when selected.

Change these defaults when the user's topology requires it, and document the
reason.
