#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DEFAULT_ALLOWED_TARGETS = {
    "workshop-memory/src/server.py",
    "workshop-memory/config.yaml",
    "workshop-memory/run.sh",
    "workshop-memory/Dockerfile",
    "workshop-memory/requirements.txt",
}

VERSION_PATTERN = re.compile(
    r'(?m)^version:\s*"(\d+)\.(\d+)\.(\d+)"\s*$'
)


class DeployError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


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


def run_command(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
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
    config_path = resolve_target(root, "workshop-memory/config.yaml")

    ensure_git_repo(root)

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
            ["git", "add", target_file, "workshop-memory/config.yaml"],
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

        require_command(["git", "push"], root, "git push failed")

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
                    "workshop-memory/config.yaml",
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

        token = os.getenv("WORKSHOP_DEPLOY_AGENT_TOKEN", "").strip()

        if not token:
            self.send_json(
                {"detail": "Deployment-agent token is not configured."},
                status_code=500,
            )
            return

        if self.headers.get("X-Workshop-Token") != token:
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
    host = os.getenv("WORKSHOP_DEPLOY_AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("WORKSHOP_DEPLOY_AGENT_PORT", "3010"))
    server = ThreadingHTTPServer((host, port), DeployHandler)

    print(
        f"Workshop deploy agent listening on http://{host}:{port}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
