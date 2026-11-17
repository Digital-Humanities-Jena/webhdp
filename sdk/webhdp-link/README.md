# @webhdp/link

A dependency-free browser/Node ES module for WebHDP-Link v1. See
[the integration guide](../../docs/guides/webhdp_link.md) for registration,
OAuth/PKCE, uploads, queueing, polling, cancellation, downloads and server use.

```sh
node --test sdk/webhdp-link/client.test.mjs
```

Serve `client.mjs` from your own application. Browser integrations need HTTPS
(except localhost/loopback), Web Crypto, Fetch, FormData and session storage.
Use a server token only in server-side code via `accessToken`; browser clients
must use `authorizationUrl()` / `completeAuthorization()`. The library never
persists access tokens. Its download method verifies bytes against SHA-256.
