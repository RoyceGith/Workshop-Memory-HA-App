# Workshop Deploy Agent

Trusted deployment agent for Workshop Memory server updates.

The add-on runs `deploy_agent.py` from a Git checkout mounted under `/share`.
By default, it expects the repository at:

`/share/Workshop-Memory-HA-App`

Before starting the add-on, make sure that checkout can commit and push:

```sh
cd /share/Workshop-Memory-HA-App
git status
git config user.name
git config user.email
git push --dry-run
```

Set `deploy_agent_token` to the same unique 32+ character token configured in
the Workshop Memory MCP add-on.

Expose this add-on only to the Home Assistant LAN/Tailscale network. Do not put
port `3010` behind the Cloudflare tunnel.
