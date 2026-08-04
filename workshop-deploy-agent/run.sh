#!/usr/bin/with-contenv bashio

set -e

export WORKSHOP_REPO_PATH="$(bashio::config 'repo_path')"
export WORKSHOP_DEPLOY_AGENT_TOKEN="$(bashio::config 'deploy_agent_token')"
export WORKSHOP_DEPLOY_AGENT_HOST="0.0.0.0"
export WORKSHOP_DEPLOY_AGENT_PORT="3010"

if [ -z "$WORKSHOP_DEPLOY_AGENT_TOKEN" ]; then
    bashio::log.fatal "deploy_agent_token is required."
    exit 1
fi

if [ ! -f "$WORKSHOP_REPO_PATH/deploy_agent.py" ]; then
    bashio::log.fatal "deploy_agent.py was not found at $WORKSHOP_REPO_PATH."
    bashio::log.fatal "Clone the repository into /share first or update repo_path."
    exit 1
fi

cd "$WORKSHOP_REPO_PATH"

exec python3 "$WORKSHOP_REPO_PATH/deploy_agent.py"
