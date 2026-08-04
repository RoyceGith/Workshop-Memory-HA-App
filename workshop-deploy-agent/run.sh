#!/usr/bin/with-contenv bashio

set -e

export WORKSHOP_REPO_PATH="$(bashio::config 'repo_path')"
export WORKSHOP_DEPLOY_AGENT_TOKEN="$(bashio::config 'deploy_agent_token')"
export WORKSHOP_DEPLOY_AGENT_HOST="0.0.0.0"
export WORKSHOP_DEPLOY_AGENT_PORT="3010"
GIT_REMOTE_URL="$(bashio::config 'git_remote_url')"
GIT_SSH_KEY_PATH="$(bashio::config 'git_ssh_key_path')"

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

if [ -n "$GIT_REMOTE_URL" ]; then
    git remote set-url origin "$GIT_REMOTE_URL"
fi

if [ -n "$GIT_SSH_KEY_PATH" ]; then
    if [ ! -f "$GIT_SSH_KEY_PATH" ]; then
        bashio::log.fatal "Git SSH key was not found at $GIT_SSH_KEY_PATH."
        bashio::log.fatal "Create an SSH deploy key under /share and add its public key to GitHub with write access."
        exit 1
    fi

    chmod 600 "$GIT_SSH_KEY_PATH"
    mkdir -p /root/.ssh
    ssh-keyscan github.com > /root/.ssh/known_hosts 2>/dev/null
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/known_hosts
    export GIT_SSH_COMMAND="ssh -i $GIT_SSH_KEY_PATH -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
fi

exec python3 "$WORKSHOP_REPO_PATH/deploy_agent.py"
