# ADR 0001: Authentication security foundation

- Status: Accepted for Day 04 implementation
- Date: 2026-10-27

## Context

SCMS is a same-origin local Docker application and a lightweight modular monolith. Authentication
must be demonstrably safe without introducing an external identity service or making Redis a source
of correctness. MySQL remains authoritative for users and refresh-token session state.

## Decision

Passwords use Argon2id through `argon2-cffi`. Encoded hashes retain their salt and cost parameters,
allowing successful login to trigger a later rehash when the policy changes. Plaintext input is
bounded to 1024 UTF-8 bytes before hashing. Product-level minimum-password rules belong to the
registration slice; this primitive does not impose character-composition rules.

Access tokens are HS256 JWTs with a ten-minute lifetime. The verifier accepts only HS256 and
requires `sub`, `iss`, `aud`, `iat`, `nbf`, `exp`, `jti`, and `token_type=access`. Signing material
is explicit configuration: an unpadded base64url value decoding to at least 32 bytes. A process must
fail configuration validation rather than generate an ephemeral key. JWT validation remains
independent of FastAPI handlers. Signed tokens must satisfy `iat <= nbf < exp`, and `exp - iat`
must be positive and no greater than 600 seconds; no implicit clock-skew tolerance is applied.

Refresh credentials are opaque values containing 32 CSPRNG bytes, encoded as unpadded base64url.
Only their SHA-256 digest crosses the persistence boundary. SHA-256 is appropriate here because the
input is uniformly random high-entropy material, unlike a human password.

One login/device session creates one refresh-token family. Slice 04.1 established this family model,
and Slice 04.3 implemented rotation on every use.
The transaction must lock the family row first and then the presented token/current-token rows in a
stable order. It creates the successor, marks the predecessor rotated, and links the chain in one
MySQL transaction. Any use of an already rotated token is strict replay detection and revokes the
whole family; no Redis lock may replace this invariant.

Strict replay handling has a known usability cost: concurrent refreshes caused by retries or
multiple tabs can make the second request look like replay and revoke the family. The browser slice
must serialize refresh attempts. The server will not retain recoverable successor plaintext or
silently allow a replay grace window unless a later ADR explicitly changes this policy.

Logout revokes the current family and clears its refresh cookie. Already issued access tokens remain
valid for at most their residual ten-minute lifetime; global denylisting is deliberately excluded
from V1. Logout-all-sessions may revoke all live families for the user in a later slice.

Authentication V1 uses a host-only, HttpOnly refresh cookie with `SameSite=Lax`, `Secure` in
production, and a narrow authentication cookie path. Refresh and logout are POST-only, and
cookie-bearing authentication endpoints validate `Origin` against an exact configured allowlist.
As an architectural recommendation, access JWTs must not be stored in localStorage.

Redis-backed rate limiting for login, registration, and refresh abuse is deferred. Redis will not
decide credential validity, rotation, revocation, or authorization correctness.

## Consequences

- Compromise of the symmetric signing key permits access-token forgery, so secret distribution and
  rotation must be controlled. Asymmetric signing is unnecessary while SCMS has one trust domain.
- Account disablement and current authorization still require application/database checks; JWT
  claims are not a durable authorization database.
- Slice 04.1 established the Argon2id, HS256 access-JWT, and opaque refresh-token primitives.
  Slices 04.2A, 04.2B, and 04.3 subsequently implemented registration; login; access-JWT and
  initial refresh-token issuance; refresh rotation and replay detection; cookie handling; logout;
  and family revocation. Redis rate limiting, access-JWT blacklisting, logout-all-sessions, cleanup
  automation, and multi-tab refresh handling remain deferred.
