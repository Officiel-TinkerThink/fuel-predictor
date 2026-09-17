# ADR 0014: Agents connect through OAuth 2.1 grants, with static credentials kept for headless use

## Status

Proposed

## Context

ADR 0008 made the application its own authorization server and gave each MCP client a static
`fpa_…` credential issued by an administrator and pasted into the client's configuration. That
works for a CI job or a server-side agent. It does not work for the case the product now has: a
planner opening Claude Code, Cursor or the Claude.ai connector on their own laptop and expecting a
"Connect" button, a browser sign-in, and a consent screen, the way every other remote MCP server
they use behaves.

The MCP authorization specification describes that flow as OAuth 2.1 with the MCP server acting
as a resource server: the server advertises where its authorization server is, the client
registers itself, the user authorizes in a browser, and the client presents a bearer token from
then on. ADR 0008 deferred dynamic client registration "until a real harness needs it". The
harnesses need it now.

Nothing else in ADR 0008 changes. The constraint that made it reject Keycloak and hosted identity
providers still holds: five users, no memory headroom for another service, and a stated
requirement that access can be revoked immediately.

## Decision

### Two ways to obtain a bearer token, one way to present it

The `/mcp` endpoint keeps accepting `Authorization: Bearer …` and nothing else. Behind that
header there are now two kinds of token, resolved in turn:

- **Agent credentials** (ADR 0008): issued by an administrator, tied to no user, long-lived,
  revoked from *Integrasi Agen*. Kept for headless agents and CI. Unchanged.
- **Agent grants** (this ADR): obtained by a signed-in user delegating some of their own access
  to a registered client. Short-lived access token with a refresh token, tied to the user *and*
  the client, revoked by the user or an administrator, and expiring on its own if neither does.

Both resolve to the same `AgentClient` principal the MCP handler already authorizes and audits
against; a grant is presented as an agent client whose name is
"`<username>` via `<client name>`" so the audit trail says which person's agent acted, not just
which program. The MCP tool surface does not know or care which kind of token arrived.

### The application is the authorization server

The authorization server is the same FastAPI process, at the same origin, reusing the existing
session and CSRF machinery for the consent step. It exposes what the MCP specification requires
and no more: protected-resource and authorization-server metadata documents, dynamic client
registration, an authorization endpoint, a token endpoint, and revocation. No external identity
provider, no JWT library, no new dependency: PKCE is a SHA-256 and a base64.

### Public clients only, PKCE mandatory, exact redirect match

Every registered client is a public client: no client secret is issued, and the token endpoint
authenticates none. A coding agent on a laptop cannot keep a secret, and pretending it can
gives no security. Proof of possession comes from PKCE with `S256`, which is required on every
authorization request; `plain` is refused. Redirect URIs must be registered at registration time,
must be `https://` or a loopback `http://` address (RFC 8252), and are matched exactly, never by
prefix.

Dynamic registration is open: anyone who can reach the server can register a client. This is safe
because registration grants nothing. A registered client only ever obtains a token after a real
user signs in and consents, and the consent screen shows the client's name and redirect host so
the user can refuse a client they do not recognize.

### A user can only delegate what they hold

The scopes a grant carries are the intersection of what the client asked for, what the user
consented to, and what the user's own role allows. A scope is delegable by a user only if their
role already holds every capability that scope confers; an operator's agent can never do more
than the operator. `models:admin` therefore requires an administrator to grant it and remains
additionally gated by configuration as ADR 0010 requires.

### Grants are opaque, hashed, and rotated

Access tokens, refresh tokens and authorization codes are random opaque strings, stored only as
SHA-256 hashes exactly like agent credentials and browser sessions. Authorization codes are
single-use and expire within minutes. Refreshing a grant rotates both its tokens and invalidates
the previous refresh token; a refresh token presented twice indicates theft and revokes the
grant. Because tokens are opaque and looked up on every call, revocation is immediate, which is
the same reason ADR 0008 chose sessions over JWTs.

## Research and adaptation

- [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
  requires OAuth 2.1, PKCE, protected-resource metadata (RFC 9728) and recommends dynamic client
  registration (RFC 7591). We implement all of it because the target clients (Claude Code, Cursor,
  Claude.ai connectors) will not connect without the discovery documents and registration.
- [OAuth 2.1 draft](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1) removes the
  implicit and password grants and mandates PKCE and exact redirect matching. We support only the
  authorization-code and refresh-token grants.
- [RFC 8252, OAuth for Native Apps](https://datatracker.ietf.org/doc/html/rfc8252) is why loopback
  `http://` redirects are allowed and why clients are public.
- [RFC 7636, PKCE](https://datatracker.ietf.org/doc/html/rfc7636) fixes the verifier length and
  the `S256` transform we verify.
- [RFC 8707, Resource Indicators](https://datatracker.ietf.org/doc/html/rfc8707): the MCP
  specification has clients send `resource` on authorization and token requests. We accept it and
  refuse a value that is not this server's `/mcp` URL, so a token minted here cannot be intended
  for elsewhere.

We rejected replacing static credentials with grants: a CI pipeline has no browser to consent in.
We rejected client secrets and confidential clients: none of the target clients can hold one. We
rejected JWT access tokens for the same reason ADR 0008 rejected JWT sessions.

## Consequences

- New tables for registered clients, authorization codes and grants, in one Alembic revision.
  Agent credentials keep their table and their UI.
- *Integrasi Agen* gains a second list: grants, showing the user, client, scopes, expiry and a
  revoke action. A user needs somewhere to see and revoke their own grants; that page is a small
  addition to the existing account surface.
- The `WWW-Authenticate` challenge on `/mcp` gains `resource_metadata`, and the two `.well-known`
  documents plus `/oauth/register` and `/oauth/token` are reachable without a session. `/oauth/authorize`
  is not: it is the one place a session is required, because that is where the user is.
- Open registration needs a rate limit and a sweep of registrations that never completed a flow,
  or the table fills with abandoned rows.
- Every client integration has quirks. The clients named above are verified against the real
  server before this ADR moves to Accepted; `docs/production/mcp-integration.md` documents the
  OAuth path beside the static one.
- Supersedes the "dynamic client registration is deferred" sentence in ADR 0008. The rest of
  ADR 0008 stands.
