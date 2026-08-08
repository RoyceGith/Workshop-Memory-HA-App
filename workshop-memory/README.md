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

For a persistent Home Assistant setup, install the separate
`Workshop Deploy Agent` add-on from this repository. Set the Workshop Memory MCP
add-on options so `deploy_agent_url` points at the Home Assistant host on port
`3010`, for example `http://<home-assistant-ip>:3010`, and
`deploy_agent_token` matches the deploy-agent add-on token.
If Home Assistant is on a different device, bind
`WORKSHOP_DEPLOY_AGENT_HOST` to the Pi's Tailscale IP instead of `0.0.0.0`.
If you must bind all interfaces, restrict port `3010` with a firewall.

## Repository inspection

The MCP server exposes read-only code inspection tools so ChatGPT can safely
find where future server changes belong before using the trusted deploy agent:

- `list_repository_files`
- `read_repository_file`
- `search_repository_code`

Configure `code_repository_path` to the Git checkout under `/share`. The tools
hide Git internals, dependency folders, bytecode, private keys, certificate/key
files, and `.env`-style files.

## Project templates

On first use, the app copies its editable project templates into the vault at:

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

Every project starts with the five-note `core` pack. New and existing projects
can also use the optional `hardware_mechatronics` or
`software_infrastructure` pack. Use `list_project_template_packs` and
`preview_project_template_pack` before applying a pack. Applying a pack creates
only missing notes and never overwrites an existing file.

New projects can select optional packs with `template_packs`. Existing projects
use `apply_project_template_pack` after explicit approval. Templates can use
Obsidian callouts, tables, Mermaid diagrams, and local embedded images.

Use `list_project_notes` to inventory a project before reorganizing it. A safe
in-place reorganization is a separate workflow:

1. `stage_project_reorganization` stores complete proposed replacements without
   changing accepted project notes and returns a compact approval summary.
2. `apply_project_reorganization` requires explicit approval and the exact draft
   SHA-256, refuses to apply if the draft or a source note changed after preview,
   archives every original, and replaces the approved set with rollback on
   failure.

Changing a master template never rewrites an existing project automatically.

ChatGPT can save PNG, JPEG, WebP, and GIF files of up to 8 MB with
`save_project_image_asset`. The tool returns the corresponding Obsidian embed,
for example `![[assets/architecture.png]]`.

Generic Markdown notes can be created anywhere beneath `Projects` with
`write_project_note`. Missing folders can be created in the same operation,
so `NOTES/HA OS Entities.md` is one write call. Create mode never overwrites;
replace mode archives the previous note, and append mode preserves its content.
Use `read_project_note` to verify a saved note. Read-only tools publish the MCP
`readOnlyHint`, allowing clients to avoid unnecessary approval prompts.
