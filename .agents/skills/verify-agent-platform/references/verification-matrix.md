# Verification matrix

Select only categories applicable to the approved design.

| Category | What to establish |
| --- | --- |
| typecheck/build | Generated packages compile and public contracts agree |
| unit | Pure registries, mappings, parsing, and error normalization work |
| runtime integration | pi adapter completes, streams, cancels, and reports usage |
| Tool integration | Grants, built-ins, delegation, limits, and cancellation work |
| Skill integration | Roots, precedence, metadata, resources, and on-demand loading work |
| Session integration | Required ordering, restart, ownership, and concurrency behavior works |
| HTTP/SSE | Validation, event order, terminal behavior, disconnect, and shutdown work |
| InsForge | Auth, identity propagation, RLS, database, and Storage contracts work |
| BFF | Opaque cookie, refresh, route allowlist, identity overwrite, and streaming work |
| MCP | Discovery, allowlist, grants, schema, failure mode, and close work |
| deployment | Private services, nginx syntax, health, migration, smoke, and rollback work |

For external integrations, distinguish hermetic adapter tests from authorized
live tests. State plainly when live evidence is unavailable.

Do not add a test merely to make the matrix look complete. Each test should
protect a claimed behavior or a likely regression.
