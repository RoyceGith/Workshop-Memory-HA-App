#!/usr/bin/env python3
from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DEFAULT_ALLOWED_TARGETS = {
    "deploy_agent.py",
    "workshop-deploy-agent/config.yaml",
    "workshop-deploy-agent/Dockerfile",
    "workshop-deploy-agent/run.sh",
    "workshop-memory/src/server.py",
    "workshop-memory/config.yaml",
    "workshop-memory/run.sh",
    "workshop-memory/Dockerfile",
    "workshop-memory/requirements.txt",
}

VERSION_PATTERN = re.compile(
    r'(?m)^version:\s*"(\d+)\.(\d+)\.(\d+)"\s*$'
)
CONFLICT_VERSION_PATTERN = re.compile(
    r'<<<<<<<[^\n]*\n'
    r'version:\s*"(\d+)\.(\d+)\.(\d+)"\s*\n'
    r'=======\n'
    r'version:\s*"(\d+)\.(\d+)\.(\d+)"\s*\n'
    r'>>>>>>>[^\n]*(?:\n|$)'
)
MIN_TOKEN_LENGTH = 32
GENERATED_STATUS_PATHS = {
    "__pycache__",
    "workshop-memory/src/__pycache__/server.cpython-314.pyc",
}
VERSION_CONFIG_PATHS = {
    "workshop-memory/config.yaml",
    "workshop-deploy-agent/config.yaml",
}


class DeployError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def deploy_token() -> str:
    token = os.getenv("WORKSHOP_DEPLOY_AGENT_TOKEN", "").strip()

    if not token:
        raise DeployError(
            "Deployment-agent token is not configured.",
            status_code=500,
        )

    if token == "replace-with-a-long-random-token" or len(token) < MIN_TOKEN_LENGTH:
        raise DeployError(
            "Deployment-agent token must be a non-placeholder value "
            f"with at least {MIN_TOKEN_LENGTH} characters.",
            status_code=500,
        )

    return token


def repo_path() -> Path:
    configured = os.getenv("WORKSHOP_REPO_PATH", "").strip()

    if configured:
        return Path(configured).expanduser().resolve()

    return Path(__file__).resolve().parent


def allowed_targets() -> set[str]:
    configured = os.getenv("WORKSHOP_ALLOWED_TARGETS", "").strip()

    if not configured:
        return set(DEFAULT_ALLOWED_TARGETS)

    return {
        item.strip().replace("\\", "/")
        for item in configured.split(",")
        if item.strip()
    }


def normalize_target(target_file: Any) -> str:
    if not isinstance(target_file, str):
        raise DeployError("target_file must be a string.")

    clean_target = target_file.strip().replace("\\", "/")

    if clean_target not in allowed_targets():
        raise DeployError(f"Target file is not permitted: {clean_target}")

    return clean_target


def resolve_target(root: Path, target_file: str) -> Path:
    root = root.resolve()
    target_path = (root / target_file).resolve()

    if target_path != root and root not in target_path.parents:
        raise DeployError("Resolved target is outside the Git repository.")

    if not target_path.is_file():
        raise DeployError(f"Target file does not exist: {target_file}")

    return target_path


def run_command(
    command: list[str],
    root: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()

    if env:
        command_env.update(env)

    return subprocess.run(
        command,
        cwd=root,
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_command(command: list[str], root: Path, failure: str) -> str:
    result = run_command(command, root)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()

        if detail:
            raise DeployError(f"{failure}: {detail}", status_code=500)

        raise DeployError(failure, status_code=500)

    return result.stdout.strip()


def git_status_entries(root: Path) -> list[tuple[str, str]]:
    """Return parsed porcelain status entries as (status, path)."""
    status = require_command(
        ["git", "status", "--porcelain"],
        root,
        "Could not read Git status",
    )
    entries: list[tuple[str, str]] = []

    for line in status.splitlines():
        if not line:
            continue

        entries.append((line[:2], line[3:].replace("\\", "/")))

    return entries


def is_generated_status_path(path: str) -> bool:
    """Return whether a dirty path is generated noise the agent may clean."""
    clean_path = path.strip().replace("\\", "/")

    return (
        clean_path in GENERATED_STATUS_PATHS
        or clean_path.endswith(".pyc")
        or "__pycache__/" in clean_path
    )


def cleanup_generated_files(root: Path) -> list[str]:
    """Clean tracked or untracked generated files that commonly block deploys."""
    cleaned: list[str] = []

    for status, path in git_status_entries(root):
        if not is_generated_status_path(path):
            continue

        target = (root / path).resolve()

        if target != root and root not in target.parents:
            continue

        if status == "??":
            if target.is_dir():
                shutil.rmtree(target)
                cleaned.append(path)
            elif target.exists():
                target.unlink()
                cleaned.append(path)
        else:
            require_command(
                ["git", "restore", "--", path],
                root,
                f"Could not restore generated file {path}",
            )
            cleaned.append(path)

    return cleaned


def ensure_git_repo(root: Path) -> None:
    result = run_command(
        ["git", "rev-parse", "--show-toplevel"],
        root,
    )

    if result.returncode != 0:
        raise DeployError(
            f"Repository path is not a Git checkout: {root}",
            status_code=500,
        )

    git_root = Path(result.stdout.strip()).resolve()

    if git_root != root:
        raise DeployError(
            f"Agent must run at the Git root. Expected {git_root}, got {root}",
            status_code=500,
        )


def resolve_version_config_conflict(root: Path, path: str) -> str:
    """Resolve a version-only config conflict by selecting max patch + 1."""
    config_path = (root / path).resolve()
    content = config_path.read_text(encoding="utf-8")
    match = CONFLICT_VERSION_PATTERN.search(content)

    if not match:
        raise DeployError(
            f"Could not automatically resolve conflict in {path}.",
            status_code=409,
        )

    left = tuple(int(match.group(index)) for index in (1, 2, 3))
    right = tuple(int(match.group(index)) for index in (4, 5, 6))
    major, minor, patch = max(left, right)
    resolved_version = f'{major}.{minor}.{patch + 1}'
    resolved_content = CONFLICT_VERSION_PATTERN.sub(
        f'version: "{resolved_version}"\n',
        content,
        count=1,
    )

    if "<<<" in resolved_content or ">>>" in resolved_content or "=======" in resolved_content:
        raise DeployError(
            f"Conflict markers remain in {path}.",
            status_code=409,
        )

    config_path.write_text(resolved_content, encoding="utf-8", newline="\n")
    require_command(
        ["git", "add", path],
        root,
        f"Could not stage resolved conflict in {path}",
    )

    return resolved_version


def attempt_version_only_rebase(root: Path) -> dict[str, Any]:
    """Rebase and resolve only add-on version-line conflicts automatically."""
    rebase = run_command(
        ["git", "rebase", "origin/main"],
        root,
        env={"GIT_EDITOR": "true"},
    )

    if rebase.returncode == 0:
        return {"status": "rebased"}

    unmerged = require_command(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        root,
        "Could not inspect rebase conflicts",
    )
    conflict_paths = [
        path.strip().replace("\\", "/")
        for path in unmerged.splitlines()
        if path.strip()
    ]

    if not conflict_paths or any(
        path not in VERSION_CONFIG_PATHS
        for path in conflict_paths
    ):
        run_command(["git", "rebase", "--abort"], root)
        raise DeployError(
            "Repository has source conflicts that require manual review. "
            "Automatic deploy recovery only resolves add-on version conflicts.",
            status_code=409,
        )

    resolved_versions = {
        path: resolve_version_config_conflict(root, path)
        for path in conflict_paths
    }

    while True:
        continued = run_command(
            ["git", "rebase", "--continue"],
            root,
            env={"GIT_EDITOR": "true"},
        )

        if continued.returncode == 0:
            break

        unmerged = require_command(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            root,
            "Could not inspect rebase conflicts",
        )
        conflict_paths = [
            path.strip().replace("\\", "/")
            for path in unmerged.splitlines()
            if path.strip()
        ]

        if not conflict_paths or any(
            path not in VERSION_CONFIG_PATHS
            for path in conflict_paths
        ):
            run_command(["git", "rebase", "--abort"], root)
            raise DeployError(
                "Repository has source conflicts that require manual review. "
                "Automatic deploy recovery only resolves add-on version conflicts.",
                status_code=409,
            )

        for path in conflict_paths:
            resolved_versions[path] = resolve_version_config_conflict(root, path)

    return {
        "status": "rebased_with_version_conflict_resolution",
        "resolved_versions": resolved_versions,
    }


def recover_and_push_committed_change(root: Path) -> dict[str, Any]:
    """Push a completed commit, recovering safe remote-moved cases."""
    first_push = run_command(["git", "push", "origin", "main"], root)

    if first_push.returncode == 0:
        return {"status": "pushed"}

    require_command(
        ["git", "fetch", "origin"],
        root,
        "git fetch origin failed after push rejection",
    )

    local_is_ancestor = run_command(
        ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
        root,
    )
    remote_is_ancestor = run_command(
        ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"],
        root,
    )

    if remote_is_ancestor.returncode == 0:
        require_command(
            ["git", "push", "origin", "main"],
            root,
            "git push retry failed",
        )
        return {"status": "push_retried"}

    if local_is_ancestor.returncode == 0:
        require_command(
            ["git", "pull", "--ff-only"],
            root,
            "git pull --ff-only after push rejection failed",
        )
        return {"status": "already_applied_upstream"}

    if local_is_ancestor.returncode == 1 and remote_is_ancestor.returncode == 1:
        rebase_result = attempt_version_only_rebase(root)
        require_command(
            ["git", "push", "origin", "main"],
            root,
            "git push after automatic rebase failed",
        )
        return {
            "status": "rebased_after_push_rejection",
            "rebase": rebase_result,
        }

    detail = (first_push.stderr or first_push.stdout).strip()
    raise DeployError(
        "git push failed and repository sync state could not be recovered"
        + (f": {detail}" if detail else ""),
        status_code=500,
    )


def preflight_git_sync(root: Path) -> dict[str, Any]:
    """Prepare the repository for deployment without asking for routine Git work."""
    cleaned_generated_files = cleanup_generated_files(root)
    status = git_status_entries(root)

    if status:
        dirty_paths = ", ".join(path for _, path in status)
        raise DeployError(
            "Repository has uncommitted non-generated changes. Refusing to "
            f"deploy before modifying files. Dirty paths: {dirty_paths}",
            status_code=409,
        )

    branch = require_command(
        ["git", "branch", "--show-current"],
        root,
        "Could not determine current Git branch",
    )

    if branch != "main":
        raise DeployError(
            f"Repository is on branch `{branch}`, not `main`. Refusing to deploy.",
            status_code=409,
        )

    require_command(
        ["git", "fetch", "origin"],
        root,
        "git fetch origin failed",
    )

    local_head = require_command(
        ["git", "rev-parse", "HEAD"],
        root,
        "Could not read local HEAD",
    )
    remote_head = require_command(
        ["git", "rev-parse", "origin/main"],
        root,
        "Could not read origin/main",
    )

    if local_head == remote_head:
        return {
            "status": "already_synced",
            "branch": branch,
            "head": local_head,
            "cleaned_generated_files": cleaned_generated_files,
        }

    local_is_ancestor = run_command(
        ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
        root,
    )
    remote_is_ancestor = run_command(
        ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"],
        root,
    )

    if local_is_ancestor.returncode == 0:
        require_command(
            ["git", "pull", "--ff-only"],
            root,
            "git pull --ff-only failed",
        )
        updated_head = require_command(
            ["git", "rev-parse", "HEAD"],
            root,
            "Could not read updated HEAD",
        )

        return {
            "status": "fast_forwarded",
            "branch": branch,
            "previous_head": local_head,
            "head": updated_head,
            "remote_head": remote_head,
            "cleaned_generated_files": cleaned_generated_files,
        }

    if remote_is_ancestor.returncode == 0:
        require_command(
            ["git", "push", "origin", "main"],
            root,
            "Could not push pending local commits",
        )
        require_command(
            ["git", "fetch", "origin"],
            root,
            "git fetch origin failed after pending push",
        )
        pushed_head = require_command(
            ["git", "rev-parse", "HEAD"],
            root,
            "Could not read local HEAD after pending push",
        )
        updated_remote_head = require_command(
            ["git", "rev-parse", "origin/main"],
            root,
            "Could not read origin/main after pending push",
        )

        if pushed_head != updated_remote_head:
            raise DeployError(
                "Pending local commits were pushed, but origin/main still does "
                "not match local HEAD. Refusing to deploy.",
                status_code=409,
            )

        return {
            "status": "pushed_pending_local_commits",
            "branch": branch,
            "head": pushed_head,
            "previous_remote_head": remote_head,
            "cleaned_generated_files": cleaned_generated_files,
        }

    if local_is_ancestor.returncode == 1 and remote_is_ancestor.returncode == 1:
        rebase_result = attempt_version_only_rebase(root)
        rebased_head = require_command(
            ["git", "rev-parse", "HEAD"],
            root,
            "Could not read HEAD after automatic rebase",
        )
        require_command(
            ["git", "push", "origin", "main"],
            root,
            "Could not push automatically rebased local commits",
        )

        return {
            **rebase_result,
            "branch": branch,
            "head": rebased_head,
            "previous_head": local_head,
            "remote_head": remote_head,
            "cleaned_generated_files": cleaned_generated_files,
        }

    raise DeployError(
        "Could not determine repository sync state. Refusing to deploy.",
        status_code=500,
    )


def validate_payload(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    target_file = normalize_target(payload.get("target_file"))
    find_text = payload.get("find_text")
    replacement_text = payload.get("replacement_text")
    reason = payload.get("reason")

    if not isinstance(find_text, str) or not find_text:
        raise DeployError("find_text cannot be empty.")

    if not isinstance(replacement_text, str):
        raise DeployError("replacement_text must be a string.")

    if find_text == replacement_text:
        raise DeployError("replacement_text must differ from find_text.")

    if not isinstance(reason, str) or not reason.strip():
        raise DeployError("A reason for the server change is required.")

    return target_file, find_text, replacement_text, reason.strip()


def config_path_for_target(root: Path, target_file: str) -> Path:
    """Return the Home Assistant add-on config whose version should be bumped."""
    if target_file == "deploy_agent.py" or target_file.startswith(
        "workshop-deploy-agent/"
    ):
        return resolve_target(root, "workshop-deploy-agent/config.yaml")

    return resolve_target(root, "workshop-memory/config.yaml")


def bump_patch_version(config_path: Path) -> tuple[str, str]:
    original_config = config_path.read_text(encoding="utf-8")
    version_match = VERSION_PATTERN.search(original_config)

    if not version_match:
        raise DeployError(
            "Could not find a valid quoted version in config.yaml.",
            status_code=500,
        )

    major = int(version_match.group(1))
    minor = int(version_match.group(2))
    patch = int(version_match.group(3))
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{patch + 1}"

    updated_config = VERSION_PATTERN.sub(
        f'version: "{new_version}"',
        original_config,
        count=1,
    )
    config_path.write_text(updated_config, encoding="utf-8", newline="\n")

    return old_version, new_version


def apply_change(payload: dict[str, Any]) -> dict[str, Any]:
    root = repo_path()
    target_file, find_text, replacement_text, reason = validate_payload(payload)
    target_path = resolve_target(root, target_file)
    config_path = config_path_for_target(root, target_file)

    ensure_git_repo(root)
    preflight_result = preflight_git_sync(root)

    original_target = target_path.read_text(encoding="utf-8")
    original_config = config_path.read_text(encoding="utf-8")

    occurrence_count = original_target.count(find_text)

    if occurrence_count == 0:
        raise DeployError("find_text was not found in the target file.")

    if occurrence_count > 1:
        raise DeployError(
            f"find_text occurs {occurrence_count} times. Exact replacement refused."
        )

    committed = False

    try:
        updated_target = original_target.replace(find_text, replacement_text)
        target_path.write_text(updated_target, encoding="utf-8", newline="\n")

        if target_file == "workshop-memory/src/server.py":
            require_command(
                [
                    sys.executable,
                    "-m",
                    "py_compile",
                    str(target_path),
                ],
                root,
                "Python validation failed",
            )

        previous_version, new_version = bump_patch_version(config_path)

        require_command(
            [
                "git",
                "add",
                target_file,
                str(config_path.relative_to(root)).replace("\\", "/"),
            ],
            root,
            "git add failed",
        )

        diff_result = run_command(["git", "diff", "--cached", "--quiet"], root)

        if diff_result.returncode == 0:
            raise DeployError("No Git changes were detected after applying the patch.")

        if diff_result.returncode not in (0, 1):
            raise DeployError("git diff failed.", status_code=500)

        commit_message = f"Apply server update {new_version}"
        require_command(
            ["git", "commit", "-m", commit_message],
            root,
            "git commit failed",
        )
        committed = True

        push_result = recover_and_push_committed_change(root)

        commit = require_command(
            ["git", "rev-parse", "--short", "HEAD"],
            root,
            "Could not read commit hash",
        )

        return {
            "status": "applied",
            "target_file": target_file,
            "reason": reason,
            "previous_version": previous_version,
            "new_version": new_version,
            "commit": commit,
            "commit_message": commit_message,
            "pushed": True,
            "preflight": preflight_result,
            "push": push_result,
            "home_assistant_update_required": True,
        }
    except Exception:
        if not committed:
            target_path.write_text(original_target, encoding="utf-8", newline="\n")
            config_path.write_text(original_config, encoding="utf-8", newline="\n")
            run_command(
                [
                    "git",
                    "restore",
                    "--staged",
                    target_file,
                    str(config_path.relative_to(root)).replace("\\", "/"),
                ],
                root,
            )
        raise


class DeployHandler(BaseHTTPRequestHandler):
    server_version = "WorkshopDeployAgent/1.0"

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_json({"detail": "Not found."}, status_code=404)
            return

        self.send_json({"status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/apply-change":
            self.send_json({"detail": "Not found."}, status_code=404)
            return

        try:
            token = deploy_token()
        except DeployError as error:
            self.send_json({"detail": str(error)}, status_code=error.status_code)
            return

        supplied_token = self.headers.get("X-Workshop-Token", "")

        if not hmac.compare_digest(supplied_token, token):
            self.send_json({"detail": "Unauthorized."}, status_code=401)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"detail": "Invalid Content-Length."}, status_code=400)
            return

        if content_length <= 0 or content_length > 1_000_000:
            self.send_json({"detail": "Invalid request size."}, status_code=400)
            return

        try:
            payload = json.loads(
                self.rfile.read(content_length).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"detail": "Invalid JSON body."}, status_code=400)
            return

        if not isinstance(payload, dict):
            self.send_json({"detail": "JSON body must be an object."}, status_code=400)
            return

        try:
            self.send_json(apply_change(payload))
        except DeployError as error:
            self.send_json(
                {"detail": str(error)},
                status_code=error.status_code,
            )
        except Exception as error:
            self.send_json(
                {"detail": f"Unexpected deployment error: {error}"},
                status_code=500,
            )

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), format % args)
        )

    def send_json(self, payload: dict[str, Any], status_code: int = 200) -> None:
        response = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def main() -> None:
    host = os.getenv("WORKSHOP_DEPLOY_AGENT_HOST", "127.0.0.1")
    port = int(os.getenv("WORKSHOP_DEPLOY_AGENT_PORT", "3010"))
    server = ThreadingHTTPServer((host, port), DeployHandler)

    print(
        f"Workshop deploy agent listening on http://{host}:{port}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
