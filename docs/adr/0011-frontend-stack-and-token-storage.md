# ADR-0011: Frontend stack and session storage

**Status:** accepted (Phase 5)

React 18 + Vite + TypeScript (strict), react-router, React Flow (agent graph), Recharts (analytics), vitest.
Dependencies are pinned exactly; the lockfile is committed. No component library and no state library: the app is
server-state-driven, so a small `useAsync` hook and one event reducer are enough.

**Tokens.** The 15-minute access token is kept only in memory. The rotating refresh token is kept in
`sessionStorage` (survives reload, dies with the tab). Trade-off: any XSS could read it, so the UI never injects
HTML (`dangerouslySetInnerHTML` is a lint error), renders generated code and model output strictly as text, and
nginx ships a restrictive CSP. An httpOnly-cookie refresh flow is a candidate for Phase 10 (needs CSRF handling).
Concurrent 401s share a single refresh call because refresh tokens rotate and replay revokes the whole family.
