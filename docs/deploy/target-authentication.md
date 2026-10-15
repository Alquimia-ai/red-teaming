# Target service authentication

The Alquimia connector accepts either an existing opaque Bearer credential or an OAuth2
client-credentials document as the **value of its resolved secret**. Run specifications still
contain only `target.connector.secret_ref`; never put this document or a token in a run spec,
catalogue, Helm values, logs or Git.

For Keycloak, provision a dedicated confidential client with service accounts enabled, browser
login and password grants disabled, and full scope disabled. Grant only the runtime audience and
the agentspace needed by the evaluation. Do not grant platform administration, realm management,
tool approval or impersonation. Runtime binds inference and worklog ownership to the service
account's subject: omit `options.user_id` rather than impersonating another user.

Provision this value through your Kubernetes Secret manager (placeholders only below):

```json
{
  "type": "oauth2_client_credentials",
  "token_endpoint": "https://identity.example/realms/production/protocol/openid-connect/token",
  "client_id": "red-teaming-runner",
  "client_secret": "<managed out of band>"
}
```

The token endpoint must use HTTPS and contain no URL credentials, query or fragment. Token
requests use `client_secret_post`. The connector caches access tokens in memory and obtains a
new one before expiry, including during worklog polling. Client credentials do not need refresh
tokens. A rejected target token invalidates the cache for the next governed attempt; the auth
layer never replays an inference. Redirects are not followed. Token endpoint failures are recorded
without its response body or credential material. Existing static Bearer secrets remain supported.

Updating a Kubernetes Secret affects newly launched runners. An already running process retains
its resolved client secret; credential rotation must retain the previous secret until existing
runners finish. Token renewal is not client-secret rotation.

Deploy the runner image containing this connector and update `images.runner` in the independent
red-teaming Helm release. Neither Runtime nor Studio needs a new image. Verify issuance and
renewal with protected read-only worklog requests; do not start a run as an authentication test.
