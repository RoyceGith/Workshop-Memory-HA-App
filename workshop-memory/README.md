# Workshop Memory MCP

Home Assistant app for running the Workshop Memory MCP server.

## Vault

The app reads and writes the synchronized Obsidian vault at:

`/share/workshop-vault`

## MCP endpoint

The server listens on port `3001`.

Endpoint:

`http://<home-assistant-ip>:3001/mcp`