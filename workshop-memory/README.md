# Workshop Memory MCP

Home Assistant app for running the Workshop Memory MCP server.

## Vault

The app reads and writes the synchronized Obsidian vault at:

`/share/workshop-vault`

## MCP endpoint

The server listens on port `3001`.

Endpoint:

`http://<home-assistant-ip>:3001/mcp`

## Server update agent

`apply_server_change` sends approved source updates to a separate deploy agent.
The agent can run on a Raspberry Pi that has the Git repository cloned.
No deploy token is committed to this repository. Use a unique random token of
at least 32 characters.
Make sure the Pi clone can commit and push first:

```sh
git status
git config user.name
git config user.email
git push --dry-run
```

On the Pi:

```sh
cd /home/pi/Workshop-Memory-HA-App
export WORKSHOP_REPO_PATH=/home/pi/Workshop-Memory-HA-App
export WORKSHOP_DEPLOY_AGENT_TOKEN='replace-with-a-long-random-token'
python3 deploy_agent.py
```

The agent listens on port `3010` by default and exposes:

- `GET /health`
- `POST /apply-change`

For systemd, copy `deploy_agent.service.example` to
`/etc/systemd/system/workshop-deploy-agent.service`, edit the paths and token,
then enable it:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now workshop-deploy-agent
```

Set the Home Assistant add-on options so `deploy_agent_url` points at the Pi,
for example `http://<pi-tailscale-ip>:3010`, and `deploy_agent_token` matches
the Pi token.
If Home Assistant is on a different device, bind
`WORKSHOP_DEPLOY_AGENT_HOST` to the Pi's Tailscale IP instead of `0.0.0.0`.
If you must bind all interfaces, restrict port `3010` with a firewall.

## Project templates

On first use, the app copies its five project templates into the vault at:

`Templates/Workshop Memory/Projects`

Templates support the following placeholders:

`project_name`, `source_session`, `discussion`, `conclusions`, `decisions`,
`useful_information`, `open_questions`, and `next_actions`.

Template changes use a review workflow: save a draft with
`save_project_template_draft`, then apply it with
`apply_project_template_draft` only after explicit user approval. Previous
template versions are retained in the template folder's `.archive` directory.
Draft validation also requires every original H2 section and source-data
placeholder, preventing visual edits from dropping project information.

New projects include an `assets/project-cover.svg` cover and can use Obsidian
callouts, tables, Mermaid diagrams, and local embedded images. Existing projects
are not changed when a master template changes.

ChatGPT can save PNG, JPEG, WebP, and GIF files of up to 8 MB with
`save_project_image_asset`. The tool returns the corresponding Obsidian embed,
for example `![[assets/architecture.png]]`.
