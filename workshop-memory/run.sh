#!/usr/bin/with-contenv bashio

export WORKSHOP_MCP_TRANSPORT=http
export WORKSHOP_MCP_HOST=0.0.0.0

export WORKSHOP_DEPLOY_AGENT_URL="$(bashio::config 'deploy_agent_url')"
export WORKSHOP_DEPLOY_AGENT_TOKEN="$(bashio::config 'deploy_agent_token')"
export WORKSHOP_CODE_REPOSITORY_PATH="$(bashio::config 'code_repository_path')"

python3 /app/src/server.py
