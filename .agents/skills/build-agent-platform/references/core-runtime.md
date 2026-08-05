# Core runtime

Use this reference while implementing Core.

## pi Runtime Adapter

Wrap `pi-agent-core` and `pi-ai` behind a small interface that:

- creates a runtime Agent from a platform `AgentDefinition`;
- maps platform model configuration to the current pi model API;
- supplies only explicitly granted Tools;
- forwards text, Tool, delegation, error, and completion events;
- accepts cancellation;
- returns normalized output, usage, and serializable state.

Inspect the installed pi version rather than relying on historical method
signatures.

## Agent Registry

Store immutable definitions keyed by stable ID. Validate duplicate IDs,
unknown Tools, unknown delegation targets, and invalid model configuration at
startup.

Do not create separate Supervisor and Subagent classes. Granting
`delegate_to_agent` makes an Agent a Supervisor. The Tool must still restrict
which registered non-Supervisor Agents it may call.

## Tool Registry

Give every Tool a stable name, description, input schema, and async executor.
Resolve Tool grants during Agent construction. Start with:

- `read`: bounded text reads;
- `write`: create or replace a file;
- `edit`: deterministic targeted edits;
- `bash`: bounded command execution with cancellation;
- `web_search`: provider-neutral result normalization;
- `delegate_to_agent`: synchronous child invocation and result return.

The target project decides its filesystem boundary and command trust model.
Do not silently introduce a sandbox. Document whether Tools run with the Agent
Server's permissions.

## Skill Registry

Discover Skill directories from configured roots, including conventional
`.codex/skills` and `.agents/skills`. Read metadata cheaply, expose available
Skills to the model, and load full instructions only when selected.

Support referenced files, scripts, and assets as ordinary Skill resources.
Resolve links inside the Skill root and define precedence for duplicate names.
Loading a Skill never grants a Tool.

## Sessions

Begin with the smallest interface the product needs: create/open, append
messages, load history/state, save state, and list or delete when required.
Use an in-memory repository for Core and an injected durable repository for
Production.

Add leases, idempotency keys, placeholders, recovery, child-run ledgers, and
Tool-call persistence only when concurrency, reconnect, billing, audit, or
restart requirements justify them.

## Agent Server and CLI

Compose dependencies once at startup. Keep handlers thin:

1. validate input and identity;
2. load the Session;
3. run the selected Agent;
4. stream normalized SSE events when requested;
5. persist the final state;
6. normalize errors and close resources.

Use a CLI as a low-friction Core interface when useful. It should call the
same application service as HTTP instead of duplicating orchestration.
