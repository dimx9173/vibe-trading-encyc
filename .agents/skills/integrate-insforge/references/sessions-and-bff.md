# Sessions and BFF

Read this reference only when durable conversations or browser access are in
scope.

## Durable Sessions

Persist what restart continuity requires:

- Session ownership and metadata;
- ordered user, assistant, and Tool messages;
- per-Agent resumable state or summaries;
- run status and usage when needed for audit or billing.

Use transactions around state transitions that must be atomic. Introduce a
lease or idempotency mechanism only when two workers may process the same
Session. Define how an interrupted turn becomes resumable, failed, or
recoverable before implementing background recovery.

Do not copy a universal repository interface. Derive methods and tables from
the target product's access patterns.

## Browser BFF

The BFF is an authentication and transport boundary:

1. authenticate against InsForge;
2. store tokens server-side;
3. issue a signed, opaque, expiring cookie;
4. refresh tokens with deduplication and rotation;
5. overwrite identity and authorization headers;
6. proxy an explicit HTTP/SSE route allowlist to one configured Agent Server;
7. clear local credentials on logout or unrecoverable refresh failure.

Keep Agent orchestration, prompts, Tool execution, and product business logic
in the Agent Server. Bound request bodies, upstream timeouts, error bodies, and
shutdown. Streaming proxies must preserve byte order and cancel only delivery
when server-side generation is designed to survive browser disconnects.
