# InsForge boundary

Confirm every endpoint and response shape against the user's deployment.
InsForge versions and local customizations may differ.

## Identity contexts

Model identity explicitly:

```ts
type UserContext = { kind: "user"; accessToken: string; userId?: string };
type SystemContext = { kind: "system"; credential: string };
```

Require one at each adapter call. Do not allow an omitted user credential to
fall back to system authority.

## Auth adapter

Expose only operations the application needs, commonly login, refresh,
logout, current identity, and health. Keep tokens request- or session-scoped.
If refresh rotates tokens, replace the pair atomically. Treat logout semantics
honestly when upstream token revocation is unavailable.

## Database adapter

Wrap PostgREST without leaking headers throughout the application:

- apply the configured read/write schema profile;
- encode relation and query components;
- attach the selected identity context;
- decode JSON, empty, and error responses consistently;
- preserve caller cancellation and bound response sizes.

Keep table names and domain queries in repositories owned by the target
project. Prefer backend RLS to application-side owner filtering.

## Storage adapter

Support only required operations such as list, read, write, and delete.
Encode bucket and object path segments separately. Define text/binary handling,
upload encoding, pagination, and size limits explicitly.

Signed or public URLs are an authorization decision, not merely string
formatting. Issue them only after ownership checks.

## Error and test boundary

Normalize HTTP status, malformed body, timeout, cancellation, transport
failure, and response-limit errors without leaking credentials or hostile
upstream bodies.

Use injected HTTP seams for unit tests. Live tests must be opt-in and must use
dedicated test identities and disposable records.
