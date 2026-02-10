# Claude Web App OAuth for AgentCore Gateway

How we connected Claude web app to the AgentCore Gateway as an MCP connector using Cognito OAuth.

## Why authorization_code (not client_credentials)

Claude web app uses the **authorization_code** OAuth flow because it runs in a browser context where a user interacts. The `client_credentials` flow is for machine-to-machine (M2M) communication where no user is present — there's no login page, just a direct token request with a client ID and secret.

Claude web app **requires** a browser-based login redirect. It cannot use `client_credentials` because:
- It needs to redirect the user to a login page (Cognito hosted UI)
- The user authenticates interactively
- Cognito redirects back to Claude's callback URL with an authorization code
- Claude exchanges the code for an access token

### Flow comparison

**client_credentials (M2M)** — used by `test_gateway.py`:
```
Client → POST /oauth2/token (client_id + secret) → Access Token
```
One step, no browser, no user interaction.

**authorization_code (browser)** — used by Claude web app:
```
1. Claude → GET /oauth2/authorize (client_id, redirect_uri, scopes)
2. Cognito → Shows login page → User enters credentials
3. Cognito → Redirect to callback URL with ?code=xxx
4. Claude → POST /oauth2/token (code + client_id + secret) → Access Token
```
Multi-step, browser redirects, user logs in.

### Cognito limitation

Cognito does not allow mixing `client_credentials` and `code` flows on the same app client. That's why we have two clients:
- `smarthome-gateway-client` — M2M, `client_credentials` grant
- `smarthome-claude-web-client` — browser, `code` grant with callback URLs

Both client IDs are listed in the gateway's `allowedClients` so tokens from either are accepted.

## The authentication flow: who talks to whom

Claude talks to **both** Cognito and the AgentCore Gateway, at different stages:

```
Phase 1: OAuth Discovery
   Claude  ──GET /.well-known/oauth-protected-resource──►  AgentCore Gateway
   Claude  ◄── { authorization_servers: [cognito_url] } ──  AgentCore Gateway
   Claude  ──GET /.well-known/openid-configuration──────►  Cognito
   Claude  ◄── { authorize_endpoint, token_endpoint, scopes_supported } ── Cognito

Phase 2: Authorization (browser redirects)
   Claude  ──redirect user to /oauth2/authorize─────────►  Cognito
   User    ──enters username + password──────────────────►  Cognito Hosted UI
   Cognito ──redirect to callback with ?code=xxx─────────►  Claude

Phase 3: Token Exchange (server-to-server)
   Claude  ──POST /oauth2/token (code, client_id, secret)──►  Cognito
   Claude  ◄── { access_token, id_token } ──────────────────  Cognito

Phase 4: MCP Communication (with token)
   Claude  ──MCP requests (Authorization: Bearer token)──►  AgentCore Gateway
   Gateway ──validates JWT against Cognito JWKS────────────  (internal)
   Gateway ──invokes Lambda──────────────────────────────►  Lambda
   Lambda  ──publishes MQTT / reads shadow───────────────►  IoT Core
```

Key points:
- The gateway only serves OAuth metadata (Phase 1) and validates tokens (Phase 4)
- All authentication happens directly between Claude and Cognito (Phases 2-3)
- The gateway never sees user credentials — it only verifies the JWT signature using Cognito's public keys (JWKS)

## Debugging the `invalid_scope` error

### The problem

After fixing the `redirect_mismatch` error (by creating a `code`-flow client with callback URLs), Claude got a new error:

```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "code: Field required"
  }
}
```

This misleading error meant Claude never received an authorization code — the Cognito authorize step failed silently.

The actual underlying error was **`invalid_scope`** (visible as a 400 response during the token exchange).

### How we found the root cause

**Step 1**: Verified Cognito config was correct — user pool, domain, user status, app client settings all looked fine.

**Step 2**: Tested the authorize endpoint directly with Python `urllib` — it returned the login page successfully, ruling out a Cognito configuration problem.

**Step 3**: Checked what scopes Claude would request. Two metadata endpoints are involved:

1. **Gateway's resource metadata** (`/.well-known/oauth-protected-resource`):
   ```json
   {
     "authorization_servers": ["https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_xxx"],
     "resource": "https://smarthome-gateway-xxx.gateway.bedrock-agentcore.eu-central-1.amazonaws.com/mcp"
   }
   ```
   No scopes listed — so Claude falls back to the authorization server's advertised scopes.

2. **Cognito's OIDC discovery** (`/.well-known/openid-configuration`):
   ```json
   {
     "scopes_supported": ["openid", "email", "phone", "profile"],
     ...
   }
   ```
   These are Cognito's **standard OIDC scopes** — always advertised regardless of what custom scopes exist on resource servers. Custom scopes like `smarthome-gateway/read` are NOT listed here.

**Step 4**: Compared advertised scopes vs. allowed scopes:
- Claude requests: `openid`, `email`, `phone`, `profile` (from OIDC discovery)
- Client allows: `openid`, `smarthome-gateway/read`, `smarthome-gateway/write`
- Mismatch: `email`, `phone`, `profile` are **not allowed** on the client → `invalid_scope`

### The fix

Added all standard OIDC scopes to the Claude web client's `AllowedOAuthScopes`:

```python
AllowedOAuthScopes=[
    "openid",
    "email",
    "phone",
    "profile",
    "smarthome-gateway/read",
    "smarthome-gateway/write",
]
```

### Lesson

When using Cognito with an OAuth client that auto-discovers scopes (like Claude's MCP connector), you must allow **all scopes that Cognito advertises in its OIDC discovery** — not just the custom resource server scopes you care about. Cognito always advertises the standard OIDC scopes, and clients that follow the discovery spec will request them.
