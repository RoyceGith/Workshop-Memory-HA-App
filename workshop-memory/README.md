# Workshop Memory MCP

Home Assistant app for running the Workshop Memory MCP server.

## Vault

The app reads and writes the synchronized Obsidian vault at:

`/share/workshop-vault`

## MCP endpoint

The server listens on port `3001`.

Endpoint:

`http://<home-assistant-ip>:3001/mcp`

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

New projects include an `assets/project-cover.svg` cover and can use Obsidian
callouts, tables, Mermaid diagrams, and local embedded images. Existing projects
are not changed when a master template changes.

ChatGPT can save PNG, JPEG, WebP, and GIF files of up to 8 MB with
`save_project_image_asset`. The tool returns the corresponding Obsidian embed,
for example `![[assets/architecture.png]]`.
