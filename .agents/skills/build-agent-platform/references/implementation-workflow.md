# Implementation workflow

## Vertical sequence

1. Establish platform-owned contracts and a fake Runtime Adapter.
2. Register one Agent and one deterministic Tool.
3. Complete one prompt through the application service.
4. Add pi integration and runtime events.
5. Add the remaining built-ins and delegation.
6. Add Skill discovery and progressive loading.
7. Add Sessions and HTTP/SSE.
8. Add optional profiles only after Core tests pass.

This sequence keeps failures local and produces a runnable slice early.

## Evidence

For each approved capability record:

- requirement;
- implementation location;
- command;
- expected result;
- observed result;
- status and remaining gap.

Use the target project's compiler, unit tests, integration tests, and smoke
checks. A generated file is not evidence that its behavior works.

## Testing guidance

Test contracts and observable behavior:

- grants prevent unregistered Tool use;
- only Agents granted `delegate_to_agent` can delegate;
- Skill metadata is cheap and bodies load on demand;
- cancellation reaches runtime and Tool execution;
- Session state reconstructs to the required level;
- SSE event ordering and terminal behavior are stable;
- Core starts with optional integrations absent.

Avoid tests that require exact private method counts, documentation sentences,
one directory layout, or a copied reference implementation.
