# Set up SSO, SCIM and MFA

Only tested against a local Keycloak and LoopForge's own SCIM client, **not** against Okta, Entra ID or Google Workspace. Expect to adjust attribute mappings.

## SSO (OpenID Connect)
Set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` (`https://<host>/api/v1/auth/sso/callback`); production requires an `https` issuer.
Authorization-code flow with PKCE, state and nonce; the ID token is verified against the provider's JWKS. An existing password account is linked only if its address was verified.

### Map groups and domains to roles
```
OIDC_GROUPS_CLAIM=groups
OIDC_GROUP_ROLE_MAP_JSON={"lf-admins": {"org": "acme-1a2b3c4d", "role": "admin"}, "lf-devs": {"org": "acme-1a2b3c4d", "role": "developer"}}
OIDC_DOMAIN_ORG_MAP_JSON={"acme.com": {"org": "acme-1a2b3c4d", "role": "viewer"}}
```
`org` is the organization **slug**. At every SSO login the user gets the highest role they qualify for; leaving all mapped groups removes the membership. Only memberships created by SSO are changed -
manual and SCIM ones are never touched, and the last admin is never removed or demoted (the skip is audited).

## SCIM 2.0 (automatic provisioning)
1. As an org admin: `POST /api/v1/orgs/{org}/scim-tokens` with `{"name": "okta"}`; copy the token (shown once).
2. In your IdP: SCIM base URL `https://<host>/api/v1/scim/v2`, authentication "Bearer token" with that token.
3. Supported: `Users` (list with `userName eq` / `externalId eq`, get, create, PATCH `active`/`externalId`, DELETE) and `Groups` (the four role groups `viewer`, `developer`, `approver`, `admin`: adding a user to a group sets their role).
Deactivating a user removes their membership of **this** organization only; if it was their last organization the account is disabled and sessions end. Passwords are not managed by SCIM; provisioned users sign in with SSO.

## MFA (TOTP)
Users enrol under account security (`POST /api/v1/auth/mfa/enroll`, then `/activate` with a code from an authenticator app; ten one-time recovery codes are shown once).
Password logins then send `mfa_code`. An organization admin can require it (`PATCH /orgs/{org}` with `{"require_mfa": true}`; you must be enrolled yourself first).
Accounts without a password (SSO/SCIM) and API tokens are exempt: their identity provider or scope owns authentication. The web login page does not yet prompt for the code (API and CLI do).
TOTP does not defeat real-time phishing relays.

See also: [operations guide](../operations.md), [security model](../security_model.md), [ADR-0024](../adr/0024-trust-at-scale.md).
