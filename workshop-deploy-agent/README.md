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

## GitHub Push Access

Use a GitHub deploy key with write access for non-interactive pushes.

Create the key on Home Assistant:

```sh
mkdir -p /share/workshop-deploy-agent
ssh-keygen -t ed25519 -f /share/workshop-deploy-agent/id_ed25519 -N ""
cat /share/workshop-deploy-agent/id_ed25519.pub
```

In GitHub, add the public key to the repository as a deploy key and enable
write access:

`Settings -> Deploy keys -> Add deploy key -> Allow write access`

Use these add-on options:

```yaml
repo_path: "/share/Workshop-Memory-HA-App"
deploy_agent_token: "your-32-plus-character-token"
git_remote_url: "git@github.com:RoyceGith/Workshop-Memory-HA-App.git"
git_ssh_key_path: "/share/workshop-deploy-agent/id_ed25519"
```

Expose this add-on only to the Home Assistant LAN/Tailscale network. Do not put
port `3010` behind the Cloudflare tunnel.
