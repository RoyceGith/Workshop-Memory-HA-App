from __future__ import annotations
import base64
import binascii
import hashlib
import os
import httpx
import json
from html import escape
from uuid import uuid4
from pathlib import Path
import re
from datetime import datetime
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations



PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"
DEFAULT_PROJECT_TEMPLATES_PATH = PROJECT_ROOT / "templates" / "project"
CORE_PROJECT_TEMPLATE_FILENAMES = (
    "Project Overview.md",
    "Requirements.md",
    "Design Decisions.md",
    "Session Handoff.md",
    "Test Log.md",
)
PROJECT_TEMPLATE_PACKS = {
    "core": CORE_PROJECT_TEMPLATE_FILENAMES,
    "hardware_mechatronics": (
        "Bill of Materials.md",
        "Wiring and Pin Map.md",
        "Mechanical Design.md",
        "Firmware Architecture.md",
        "Communication Protocol.md",
        "Safety and Interlocks.md",
        "Calibration Data.md",
        "Build and Assembly Log.md",
    ),
    "software_infrastructure": (
        "Architecture.md",
        "API and Integrations.md",
        "Data and Storage.md",
        "Deployment and Operations.md",
        "Security and Permissions.md",
        "Release and Change Log.md",
    ),
}
PROJECT_TEMPLATE_FILENAMES = tuple(
    dict.fromkeys(
        filename
        for filenames in PROJECT_TEMPLATE_PACKS.values()
        for filename in filenames
    )
)
PROJECT_TEMPLATE_FIELDS = {
    "project_name",
    "source_session",
    "discussion",
    "conclusions",
    "decisions",
    "useful_information",
    "open_questions",
    "next_actions",
}
PROJECT_TEMPLATE_REQUIREMENTS = {
    "Project Overview.md": {
        "headings": (
            "Objective",
            "Current Stage",
            "Background",
            "Current Knowledge",
            "Open Questions",
            "Next Actions",
            "Source Session",
            "Review Status",
        ),
        "placeholders": (
            "project_name",
            "conclusions",
            "discussion",
            "useful_information",
            "open_questions",
            "next_actions",
            "source_session",
        ),
    },
    "Requirements.md": {
        "headings": (
            "Project Goal",
            "Initial Requirements",
            "Open Requirements",
            "Constraints",
            "Acceptance Criteria",
            "Source Session",
            "Review Status",
        ),
        "placeholders": (
            "project_name",
            "conclusions",
            "useful_information",
            "open_questions",
            "source_session",
        ),
    },
    "Design Decisions.md": {
        "headings": (
            "Proposed Decisions from Source Session",
            "Review Status",
        ),
        "placeholders": (
            "project_name",
            "decisions",
        ),
    },
    "Session Handoff.md": {
        "headings": (
            "Current Project Stage",
            "Current Working State",
            "Background",
            "Conclusions Reached",
            "Open Questions",
            "Next Actions",
            "Review Status",
        ),
        "placeholders": (
            "project_name",
            "source_session",
            "discussion",
            "conclusions",
            "open_questions",
            "next_actions",
        ),
    },
    "Test Log.md": {
        "headings": (
            "Current Test Status",
            "Source Session",
            "Review Status",
        ),
        "placeholders": (
            "project_name",
            "source_session",
        ),
    },
}
OPTIONAL_PROJECT_TEMPLATE_HEADINGS = {
    "Bill of Materials.md": (
        "Scope", "Selected Parts", "Candidate Parts", "Procurement",
        "Compatibility Checks", "Cost Summary", "Review Status",
    ),
    "Wiring and Pin Map.md": (
        "Electrical Architecture", "Power Rails", "Connection Table",
        "Controller Pin Map", "Wire and Connector Specifications",
        "Grounding and Noise Control", "Verification", "Review Status",
    ),
    "Mechanical Design.md": (
        "Mechanical Objective", "Dimensions and Envelope", "Mechanisms",
        "Materials and Processes", "CAD and Manufacturing Files",
        "Tolerances and Serviceability", "Open Mechanical Questions",
        "Review Status",
    ),
    "Firmware Architecture.md": (
        "Firmware Scope", "Targets and Toolchains", "Module Map",
        "State Machines and Data Flow", "Configuration and Persistence",
        "Fault Handling and Recovery", "Source References", "Review Status",
    ),
    "Communication Protocol.md": (
        "Protocol Scope", "Physical and Transport Layer", "Message Format",
        "Commands and Events", "Validation and Error Handling",
        "Timing and Recovery", "Examples", "Review Status",
    ),
    "Safety and Interlocks.md": (
        "Safety Scope", "Hazards", "Interlocks", "Fault Responses",
        "Emergency and Recovery Procedures", "Verification Checklist",
        "Residual Risks", "Review Status",
    ),
    "Calibration Data.md": (
        "Calibration Scope", "Equipment and References", "Parameters",
        "Procedure", "Results", "Acceptance Limits", "Calibration History",
        "Review Status",
    ),
    "Build and Assembly Log.md": (
        "Current Build State", "Revision Identification", "Assembly Plan",
        "Build Entries", "Rework and Deviations", "Inspection Checklist",
        "Next Build Actions", "Review Status",
    ),
    "Architecture.md": (
        "System Scope", "Component Map", "Runtime and Data Flow",
        "External Dependencies", "Boundaries and Failure Modes",
        "Architecture References", "Review Status",
    ),
    "API and Integrations.md": (
        "Integration Scope", "External Systems", "Interfaces and Endpoints",
        "Authentication and Permissions", "Contracts and Schemas",
        "Failure Handling", "Integration Test Status", "Review Status",
    ),
    "Data and Storage.md": (
        "Data Scope", "Sources of Truth", "Data Model", "Storage Locations",
        "Retention and Backups", "Privacy and Sensitive Data",
        "Migration and Recovery", "Review Status",
    ),
    "Deployment and Operations.md": (
        "Deployment Scope", "Environments", "Installation and Updates",
        "Configuration", "Health and Observability", "Backup and Rollback",
        "Operational Runbook", "Review Status",
    ),
    "Security and Permissions.md": (
        "Security Scope", "Trust Boundaries", "Identity and Authentication",
        "Authorization and Approval", "Secrets and Sensitive Data",
        "Threats and Mitigations", "Security Verification", "Review Status",
    ),
    "Release and Change Log.md": (
        "Current Release", "Release Policy", "Release History",
        "Pending Release", "Compatibility and Migration Notes",
        "Rollback References", "Review Status",
    ),
}
for _template_name, _headings in OPTIONAL_PROJECT_TEMPLATE_HEADINGS.items():
    PROJECT_TEMPLATE_REQUIREMENTS[_template_name] = {
        "headings": _headings,
        "placeholders": ("project_name",),
    }
PROJECT_TEMPLATE_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
MAX_PROJECT_TEMPLATE_SIZE = 200_000
MAX_GENERIC_PROJECT_NOTE_SIZE = 1_000_000
MAX_PROJECT_IMAGE_SIZE = 8 * 1024 * 1024
PROJECT_IMAGE_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
    ".gif": (b"GIF87a", b"GIF89a"),
}
CODE_SEARCH_ALLOWED_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".vbs",
    ".yaml",
    ".yml",
}
CODE_SEARCH_ALLOWED_FILENAMES = {
    ".gitignore",
    "Dockerfile",
}
CODE_SEARCH_BLOCKED_NAMES = {
    ".env",
    ".netrc",
    "authorized_keys",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "known_hosts",
}
CODE_SEARCH_BLOCKED_PARTS = {
    ".git",
    ".ssh",
    "__pycache__",
    "node_modules",
}
CODE_SEARCH_BLOCKED_SUFFIXES = {
    ".crt",
    ".der",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
}
MAX_CODE_FILE_READ_BYTES = 200_000
MAX_CODE_SEARCH_RESULTS = 100
MAX_CODE_LIST_RESULTS = 1_000
PROGRESS_FEED_MARKER = "<!-- workshop-progress-feed:newest-first -->"

mcp = FastMCP(
    "Workshop Memory MCP",
    host=os.getenv("WORKSHOP_MCP_HOST", "127.0.0.1"),
    port=3001,
    stateless_http=True,
    json_response=True,
)

READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
)


def load_settings() -> dict[str, Any]:
    """Load and validate the MCP server configuration."""
    if not SETTINGS_PATH.exists():
        raise FileNotFoundError(
            f"Settings file was not found: {SETTINGS_PATH}"
        )

    try:
        settings = json.loads(
            SETTINGS_PATH.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Settings file contains invalid JSON: {exc}"
        ) from exc

    required_keys = {
        "vault_path",
        "profile_summary",
        "projects_folder",
        "sessions_inbox",
        "sessions_active",
        "sessions_archive",
    }

    missing_keys = sorted(required_keys - settings.keys())

    if missing_keys:
        raise ValueError(
            "Missing required settings: " + ", ".join(missing_keys)
        )

    vault_path = Path(settings["vault_path"]).expanduser().resolve()

    if not vault_path.exists():
        raise FileNotFoundError(
            f"Vault path does not exist: {vault_path}"
        )

    if not vault_path.is_dir():
        raise NotADirectoryError(
            f"Vault path is not a directory: {vault_path}"
        )

    settings["vault_path"] = str(vault_path)
    return settings


def code_repository_root() -> Path:
    """Resolve the configured read-only code repository root."""
    configured_path = os.getenv(
        "WORKSHOP_CODE_REPOSITORY_PATH",
        "",
    ).strip()

    root = (
        Path(configured_path).expanduser()
        if configured_path
        else PROJECT_ROOT.parent
    ).resolve()

    if not root.exists():
        raise FileNotFoundError(
            f"Code repository path does not exist: {root}"
        )

    if not root.is_dir():
        raise NotADirectoryError(
            f"Code repository path is not a directory: {root}"
        )

    return root


def normalize_repository_relative_path(relative_path: str) -> str:
    """Normalize a repository-relative path without allowing traversal."""
    if not isinstance(relative_path, str):
        raise ValueError("Repository path must be a string.")

    normalized = relative_path.strip().replace("\\", "/").strip("/")

    if normalized in {"", "."}:
        return ""

    path = Path(normalized)

    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Repository path must stay inside the repository.")

    return normalized


def resolve_repository_path(relative_path: str = "") -> Path:
    """Resolve a safe repository-relative path."""
    root = code_repository_root()
    normalized = normalize_repository_relative_path(relative_path)
    resolved_path = (root / normalized).resolve()

    if resolved_path != root and root not in resolved_path.parents:
        raise ValueError("Resolved path is outside the repository.")

    return resolved_path


def is_repository_path_blocked(path: Path) -> bool:
    """Return whether a path should be hidden from code-reading tools."""
    relative_parts = [
        part.casefold()
        for part in path.relative_to(code_repository_root()).parts
    ]
    name = path.name.casefold()
    suffix = path.suffix.casefold()

    return (
        any(part in CODE_SEARCH_BLOCKED_PARTS for part in relative_parts)
        or name in CODE_SEARCH_BLOCKED_NAMES
        or suffix in CODE_SEARCH_BLOCKED_SUFFIXES
        or name.endswith(".env")
    )


def is_repository_text_file(path: Path) -> bool:
    """Return whether a file is eligible for read-only code inspection."""
    return (
        path.is_file()
        and not is_repository_path_blocked(path)
        and (
            path.suffix.casefold() in CODE_SEARCH_ALLOWED_SUFFIXES
            or path.name in CODE_SEARCH_ALLOWED_FILENAMES
        )
    )


def repository_relative_path(path: Path) -> str:
    """Return a stable POSIX-style repository-relative path."""
    return path.relative_to(code_repository_root()).as_posix()


def project_templates_path(create: bool = True) -> Path:
    """Resolve and optionally initialize editable templates in the vault."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    configured_path = settings.get(
        "project_templates_folder",
        "Templates/Workshop Memory/Projects",
    )
    templates_path = (vault_path / configured_path).resolve()

    if templates_path != vault_path and vault_path not in templates_path.parents:
        raise ValueError("Project templates folder must be inside the vault.")

    if not create:
        return templates_path

    templates_path.mkdir(parents=True, exist_ok=True)

    for filename in PROJECT_TEMPLATE_FILENAMES:
        source_path = DEFAULT_PROJECT_TEMPLATES_PATH / filename
        target_path = templates_path / filename

        if target_path.exists():
            continue

        if not source_path.is_file():
            raise FileNotFoundError(
                f"Bundled project template was not found: {source_path}"
            )

        target_path.write_text(
            source_path.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )

    return templates_path


def resolve_project_template(template_name: str) -> Path:
    """Resolve one of the supported project templates safely."""
    clean_name = clean_single_line(template_name, "Template name")

    if clean_name not in PROJECT_TEMPLATE_FILENAMES:
        raise ValueError(
            "Unknown project template. Expected one of: "
            + ", ".join(PROJECT_TEMPLATE_FILENAMES)
        )

    return project_templates_path() / clean_name


def validate_project_template(
    template_name: str,
    content: str,
) -> list[str]:
    """Validate a template's required structure and placeholders."""
    if template_name not in PROJECT_TEMPLATE_REQUIREMENTS:
        raise ValueError(f"Unknown project template: {template_name}")

    if not content.strip():
        raise ValueError("Project template content cannot be empty.")

    if len(content.encode("utf-8")) > MAX_PROJECT_TEMPLATE_SIZE:
        raise ValueError("Project template is larger than 200 KB.")

    fields = sorted(set(PROJECT_TEMPLATE_PATTERN.findall(content)))
    unknown_fields = sorted(set(fields) - PROJECT_TEMPLATE_FIELDS)

    if unknown_fields:
        raise ValueError(
            "Unknown project template placeholders: "
            + ", ".join(unknown_fields)
        )

    requirements = PROJECT_TEMPLATE_REQUIREMENTS[template_name]
    missing_fields = sorted(
        set(requirements["placeholders"]) - set(fields)
    )

    if missing_fields:
        raise ValueError(
            "Project template is missing required placeholders: "
            + ", ".join(f"{{{{{field}}}}}" for field in missing_fields)
        )

    missing_headings = [
        heading
        for heading in requirements["headings"]
        if not re.search(
            rf"^##\s+{re.escape(heading)}\s*$",
            content,
            flags=re.MULTILINE,
        )
    ]

    if missing_headings:
        raise ValueError(
            "Project template is missing required H2 sections: "
            + ", ".join(missing_headings)
        )

    return fields


def render_project_template(
    template_name: str,
    content: str,
    values: dict[str, str],
) -> str:
    """Render a validated project template using known literal fields."""
    validate_project_template(template_name, content)

    def replace_field(match: re.Match[str]) -> str:
        value = values.get(match.group(1), "Not documented")
        line_start = content.rfind("\n", 0, match.start()) + 1

        if content[line_start:match.start()] == "> ":
            return value.replace("\n", "\n> ")

        return value

    return PROJECT_TEMPLATE_PATTERN.sub(replace_field, content).rstrip() + "\n"


def create_project_cover(project_path: Path, project_name: str) -> str:
    """Create a lightweight, local SVG cover for an Obsidian project."""
    assets_path = project_path / "assets"
    assets_path.mkdir()
    cover_path = assets_path / "project-cover.svg"
    display_name = project_name[:64]
    title_font_size = min(
        52,
        max(18, int(780 / max(len(display_name) * 0.6, 1))),
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="300" viewBox="0 0 1200 300" role="img" aria-labelledby="title desc">
  <title id="title">{escape(display_name)} project cover</title>
  <desc id="desc">Workshop Memory project dashboard cover</desc>
  <rect width="1200" height="300" fill="#172126"/>
  <rect x="0" y="0" width="18" height="300" fill="#20a39e"/>
  <rect x="18" y="252" width="1182" height="48" fill="#ffba49"/>
  <circle cx="1040" cy="92" r="64" fill="#ef5b5b"/>
  <path d="M930 196h220M970 226h180" stroke="#d8e2dc" stroke-width="10" stroke-linecap="round"/>
  <text x="72" y="112" fill="#9fd8d5" font-family="Arial, sans-serif" font-size="24">WORKSHOP MEMORY</text>
  <text x="72" y="184" fill="#ffffff" font-family="Arial, sans-serif" font-size="{title_font_size}" font-weight="700">{escape(display_name)}</text>
  <text x="72" y="278" fill="#172126" font-family="Arial, sans-serif" font-size="20" font-weight="700">PROJECT DASHBOARD</text>
</svg>
"""
    cover_path.write_text(svg, encoding="utf-8", newline="\n")
    return str(cover_path)


def validate_project_image(filename: str, image_data: bytes) -> str:
    """Validate a safe project image filename, size, and file signature."""
    clean_filename = clean_single_line(filename, "Image filename")

    if safe_filename_part(clean_filename) != clean_filename:
        raise ValueError("Image filename contains unsafe characters.")

    extension = Path(clean_filename).suffix.lower()

    if extension not in PROJECT_IMAGE_SIGNATURES:
        raise ValueError("Image must be PNG, JPEG, WebP, or GIF.")

    if not image_data:
        raise ValueError("Image content cannot be empty.")

    if len(image_data) > MAX_PROJECT_IMAGE_SIZE:
        raise ValueError("Project image is larger than 8 MB.")

    if extension == ".webp":
        valid_signature = (
            image_data.startswith(b"RIFF")
            and len(image_data) >= 12
            and image_data[8:12] == b"WEBP"
        )
    else:
        valid_signature = any(
            image_data.startswith(signature)
            for signature in PROJECT_IMAGE_SIGNATURES[extension]
        )

    if not valid_signature:
        raise ValueError(
            "Image content does not match its filename extension."
        )

    return clean_filename


@mcp.tool(annotations=READ_ONLY_TOOL)
def check_server_status() -> dict[str, Any]:
    """Check whether the server can load its settings and access the vault."""
    try:
        settings = load_settings()
    except Exception as exc:
        return {
            "server": "Workshop Memory MCP",
            "status": "unhealthy",
            "settings_file": str(SETTINGS_PATH),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    vault_path = Path(settings["vault_path"])

    checked_paths: dict[str, dict[str, Any]] = {}

    for key in (
        "profile_summary",
        "projects_folder",
        "sessions_inbox",
        "sessions_active",
        "sessions_archive",
    ):
        path = vault_path / settings[key]

        checked_paths[key] = {
            "path": str(path),
            "exists": path.exists(),
            "is_file": path.is_file(),
            "is_directory": path.is_dir(),
        }

    return {
        "server": "Workshop Memory MCP",
        "status": "ok",
        "settings_file": str(SETTINGS_PATH),
        "vault_path": str(vault_path),
        "paths": checked_paths,
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def list_repository_files(
    path_prefix: str = "",
    max_results: int = 500,
) -> dict[str, Any]:
    """
    List safe, read-only source files from the configured code repository.

    Secret-like paths, private keys, Git internals, bytecode, and dependency
    folders are hidden.
    """
    root = code_repository_root()
    start_path = resolve_repository_path(path_prefix)

    if is_repository_path_blocked(start_path):
        raise PermissionError("Repository path is blocked.")

    if not start_path.exists():
        raise FileNotFoundError(
            f"Repository path was not found: {path_prefix}"
        )

    limit = max(1, min(int(max_results), MAX_CODE_LIST_RESULTS))
    files: list[dict[str, Any]] = []

    candidates = (
        [start_path]
        if start_path.is_file()
        else sorted(
            item
            for item in start_path.rglob("*")
            if item.is_file()
        )
    )

    for candidate in candidates:
        if not is_repository_text_file(candidate):
            continue

        files.append(
            {
                "path": repository_relative_path(candidate),
                "size_bytes": candidate.stat().st_size,
            }
        )

        if len(files) >= limit:
            break

    return {
        "repository_root": str(root),
        "path_prefix": normalize_repository_relative_path(path_prefix),
        "count": len(files),
        "max_results": limit,
        "truncated": len(files) >= limit,
        "files": files,
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def read_repository_file(
    relative_path: str,
    max_bytes: int = 100_000,
) -> dict[str, Any]:
    """
    Read one safe source file from the configured repository.

    This is read-only and refuses blocked secret/key paths and oversized reads.
    """
    path = resolve_repository_path(relative_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Repository file was not found: {relative_path}"
        )

    if not is_repository_text_file(path):
        raise PermissionError(
            "Repository file is not permitted for code inspection."
        )

    file_size = path.stat().st_size
    limit = max(1, min(int(max_bytes), MAX_CODE_FILE_READ_BYTES))

    with path.open("rb") as source_file:
        data = source_file.read(limit + 1)

    truncated = len(data) > limit
    data = data[:limit]

    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Repository file is not valid UTF-8 text.") from exc

    return {
        "path": repository_relative_path(path),
        "size_bytes": file_size,
        "bytes_returned": len(data),
        "max_bytes": limit,
        "truncated": truncated,
        "content": content,
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def search_repository_code(
    query: str,
    path_prefix: str = "",
    case_sensitive: bool = False,
    max_results: int = 50,
    context_lines: int = 1,
) -> dict[str, Any]:
    """
    Search safe repository source files for a literal text query.

    This is read-only, does not use regex, and limits result count and context.
    """
    clean_query = query.strip()

    if not clean_query:
        raise ValueError("Search query cannot be empty.")

    if len(clean_query) > 200:
        raise ValueError("Search query must be 200 characters or fewer.")

    start_path = resolve_repository_path(path_prefix)

    if is_repository_path_blocked(start_path):
        raise PermissionError("Repository path is blocked.")

    if not start_path.exists():
        raise FileNotFoundError(
            f"Repository path was not found: {path_prefix}"
        )

    limit = max(1, min(int(max_results), MAX_CODE_SEARCH_RESULTS))
    context = max(0, min(int(context_lines), 5))
    needle = clean_query if case_sensitive else clean_query.casefold()
    matches: list[dict[str, Any]] = []

    candidates = (
        [start_path]
        if start_path.is_file()
        else sorted(
            item
            for item in start_path.rglob("*")
            if item.is_file()
        )
    )

    for candidate in candidates:
        if not is_repository_text_file(candidate):
            continue

        if candidate.stat().st_size > MAX_CODE_FILE_READ_BYTES:
            continue

        try:
            content = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        lines = content.splitlines()

        for index, line in enumerate(lines):
            haystack = line if case_sensitive else line.casefold()

            if needle not in haystack:
                continue

            start = max(0, index - context)
            end = min(len(lines), index + context + 1)

            matches.append(
                {
                    "path": repository_relative_path(candidate),
                    "line": index + 1,
                    "text": line[:500],
                    "context": [
                        {
                            "line": line_index + 1,
                            "text": lines[line_index][:500],
                        }
                        for line_index in range(start, end)
                    ],
                }
            )

            if len(matches) >= limit:
                return {
                    "repository_root": str(code_repository_root()),
                    "query": clean_query,
                    "path_prefix": normalize_repository_relative_path(
                        path_prefix
                    ),
                    "case_sensitive": case_sensitive,
                    "count": len(matches),
                    "max_results": limit,
                    "truncated": True,
                    "matches": matches,
                }

    return {
        "repository_root": str(code_repository_root()),
        "query": clean_query,
        "path_prefix": normalize_repository_relative_path(path_prefix),
        "case_sensitive": case_sensitive,
        "count": len(matches),
        "max_results": limit,
        "truncated": False,
        "matches": matches,
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_profile_summary() -> dict[str, Any]:
    """Return the compact user workflow and preferences summary."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"])
    profile_path = vault_path / settings["profile_summary"]

    if not profile_path.exists():
        raise FileNotFoundError(
            f"Profile summary was not found: {profile_path}"
        )

    return {
        "path": str(profile_path),
        "content": profile_path.read_text(encoding="utf-8"),
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def list_projects() -> dict[str, Any]:
    """List available project folders in the Obsidian vault."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"])
    projects_path = vault_path / settings["projects_folder"]

    if not projects_path.exists():
        raise FileNotFoundError(
            f"Projects folder was not found: {projects_path}"
        )

    if not projects_path.is_dir():
        raise NotADirectoryError(
            f"Projects path is not a directory: {projects_path}"
        )

    projects = sorted(
        item.name
        for item in projects_path.iterdir()
        if item.is_dir() and not item.name.startswith(".")
    )

    return {
        "projects_folder": str(projects_path),
        "count": len(projects),
        "projects": projects,
    }

def resolve_project_folder(project: str) -> Path:
    """Resolve a project name safely inside the configured Projects folder."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"])
    projects_path = (vault_path / settings["projects_folder"]).resolve()

    project_name = project.strip()
    if not project_name:
        raise ValueError("Project name cannot be empty.")

    project_path = (projects_path / project_name).resolve()

    if project_path.parent != projects_path:
        raise ValueError("Invalid project name or path.")

    if not project_path.exists():
        raise FileNotFoundError(f"Project was not found: {project_name}")

    if not project_path.is_dir():
        raise NotADirectoryError(
            f"Project path is not a directory: {project_path}"
        )

    return project_path


def projects_root_path() -> Path:
    """Return the configured Projects root, constrained to the vault."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    projects_path = (vault_path / settings["projects_folder"]).resolve()
    if projects_path != vault_path and vault_path not in projects_path.parents:
        raise ValueError("Projects folder must stay inside the vault.")
    if not projects_path.is_dir():
        raise FileNotFoundError(f"Projects folder was not found: {projects_path}")
    return projects_path


def normalize_project_note_path(relative_path: str) -> str:
    """Normalize one Markdown path beneath Projects without traversal."""
    if not isinstance(relative_path, str):
        raise ValueError("Project note path must be a string.")
    normalized = relative_path.strip().replace("\\", "/").strip("/")
    if not normalized:
        raise ValueError("Project note path cannot be empty.")
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Project note path must stay inside Projects.")
    if any(not part or part.startswith(".") for part in candidate.parts):
        raise ValueError("Hidden or empty project-note path parts are not allowed.")
    if candidate.suffix.casefold() != ".md":
        raise ValueError("Generic project notes must use the .md extension.")
    return candidate.as_posix()


def resolve_project_note_path(relative_path: str) -> Path:
    """Resolve a generic project note safely beneath Projects."""
    projects_path = projects_root_path()
    normalized = normalize_project_note_path(relative_path)
    note_path = (projects_path / normalized).resolve()
    if projects_path not in note_path.parents:
        raise ValueError("Resolved project note path is outside Projects.")
    return note_path


@mcp.tool(annotations=READ_ONLY_TOOL)
def read_project_note(relative_path: str) -> dict[str, Any]:
    """Read any Markdown note by its path relative to the Projects folder."""
    note_path = resolve_project_note_path(relative_path)
    if not note_path.is_file():
        raise FileNotFoundError(f"Project note was not found: {relative_path}")
    return {
        "status": "ok",
        "relative_path": note_path.relative_to(projects_root_path()).as_posix(),
        "path": str(note_path),
        "content": note_path.read_text(encoding="utf-8"),
    }


@mcp.tool()
def write_project_note(
    relative_path: str,
    content: str,
    mode: Literal["create", "replace", "append"] = "create",
    create_folders: bool = True,
) -> dict[str, Any]:
    """
    Write one Markdown note beneath Projects and optionally create its folders.

    Create refuses existing files. Replace archives the prior note. Append
    preserves existing content. MCP clients should approval-gate this tool.
    """
    if not isinstance(content, str):
        raise ValueError("Project note content must be text.")
    if len(content.encode("utf-8")) > MAX_GENERIC_PROJECT_NOTE_SIZE:
        raise ValueError("Project note is larger than 1 MB.")
    note_path = resolve_project_note_path(relative_path)
    projects_path = projects_root_path()
    missing_folders: list[str] = []
    current = note_path.parent
    while current != projects_path and not current.exists():
        missing_folders.append(current.relative_to(projects_path).as_posix())
        current = current.parent
    existed = note_path.exists()
    if existed and not note_path.is_file():
        raise IsADirectoryError(f"Project note path is not a file: {relative_path}")
    if mode == "create" and existed:
        raise FileExistsError(f"Project note already exists: {relative_path}")
    if mode in {"replace", "append"} and not existed:
        raise FileNotFoundError(f"Project note was not found: {relative_path}")
    if missing_folders and not create_folders:
        raise FileNotFoundError(
            "Project note folder does not exist: " + missing_folders[-1]
        )
    if mode == "append":
        existing = note_path.read_text(encoding="utf-8")
        separator = "" if not existing or existing.endswith("\n") else "\n"
        final_content = existing + separator + content
    else:
        final_content = content
    if final_content and not final_content.endswith("\n"):
        final_content += "\n"
    if len(final_content.encode("utf-8")) > MAX_GENERIC_PROJECT_NOTE_SIZE:
        raise ValueError("Final project note is larger than 1 MB.")

    note_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if mode == "replace":
        archive_path = note_path.parent / ".archive"
        archive_path.mkdir(exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = archive_path / f"{note_path.stem} {timestamp}.md"
        backup_path.write_text(
            note_path.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
    note_path.write_text(final_content, encoding="utf-8", newline="\n")

    return {
        "status": "created" if not existed else {"replace": "replaced", "append": "appended"}[mode],
        "relative_path": note_path.relative_to(projects_path).as_posix(),
        "path": str(note_path),
        "created_folders": list(reversed(missing_folders)),
        "size_bytes": len(final_content.encode("utf-8")),
        "backup_path": str(backup_path) if backup_path else None,
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_project_summary(project: str) -> dict[str, Any]:
    """Return the Project Overview note for a named project."""
    project_path = resolve_project_folder(project)
    overview_path = project_path / "Project Overview.md"

    if not overview_path.exists():
        raise FileNotFoundError(
            f"Project Overview.md was not found for: {project}"
        )

    return {
        "project": project_path.name,
        "path": str(overview_path),
        "content": overview_path.read_text(encoding="utf-8"),
    }

def read_note(project_path: Path, filename: str) -> dict[str, Any]:
    """Read a project note and return its path, availability, and content."""
    note_path = project_path / filename

    if not note_path.exists():
        return {
            "filename": filename,
            "path": str(note_path),
            "exists": False,
            "content": None,
        }

    if not note_path.is_file():
        return {
            "filename": filename,
            "path": str(note_path),
            "exists": False,
            "content": None,
        }

    return {
        "filename": filename,
        "path": str(note_path),
        "exists": True,
        "content": note_path.read_text(encoding="utf-8"),
    }


def extract_open_decisions(content: str | None) -> list[dict[str, str]]:
    """Extract design-decision sections whose status is Open or Proposed."""
    if not content:
        return []

    decisions: list[dict[str, str]] = []
    sections = content.split("\n## DD-")

    for index, section in enumerate(sections):
        if index == 0:
            continue

        section = "## DD-" + section
        lines = section.splitlines()

        title = lines[0].removeprefix("## ").strip()
        status = ""

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("- **Status:**"):
                status = stripped.removeprefix("- **Status:**").strip()
                break

        if status.casefold() in {"open", "proposed"}:
            decisions.append(
                {
                    "title": title,
                    "status": status,
                    "content": section.strip(),
                }
            )

    return decisions


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_project_context(
    project: str,
    include_requirements: bool = True,
) -> dict[str, Any]:
    """
    Return compact context for starting or resuming work on a project.

    Includes the user profile, project overview, latest session handoff,
    unresolved design decisions, and optionally project requirements.
    """
    settings = load_settings()
    vault_path = Path(settings["vault_path"])
    project_path = resolve_project_folder(project)

    profile_path = vault_path / settings["profile_summary"]

    if not profile_path.exists() or not profile_path.is_file():
        raise FileNotFoundError(
            f"Profile summary was not found: {profile_path}"
        )

    overview = read_note(project_path, "Project Overview.md")
    handoff = read_note(project_path, "Session Handoff.md")
    design_decisions = read_note(project_path, "Design Decisions.md")

    requirements: dict[str, Any] | None = None

    if include_requirements:
        requirements = read_note(project_path, "Requirements.md")

    missing_recommended_notes = [
        note["filename"]
        for note in (overview, handoff, design_decisions)
        if not note["exists"]
    ]

    return {
        "project": project_path.name,
        "project_folder": str(project_path),
        "context_loading_order": [
            "Profile Summary",
            "Project Overview",
            "Session Handoff",
            "Open or Proposed Design Decisions",
            *(
                ["Requirements"]
                if include_requirements
                else []
            ),
        ],
        "profile_summary": {
            "path": str(profile_path),
            "content": profile_path.read_text(encoding="utf-8"),
        },
        "project_overview": overview,
        "session_handoff": handoff,
        "open_decisions": extract_open_decisions(
            design_decisions["content"]
        ),
        "requirements": requirements,
        "missing_recommended_notes": missing_recommended_notes,
    }

def clean_single_line(value: str, field_name: str) -> str:
    """Validate and normalize a required single-line text value."""
    cleaned = " ".join(value.strip().split())

    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty.")

    if len(cleaned) > 200:
        raise ValueError(
            f"{field_name} must be 200 characters or fewer."
        )

    return cleaned


def safe_filename_part(value: str) -> str:
    """Convert text into a Windows-safe filename component."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "-", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")

    if not cleaned:
        return "Session"

    return cleaned[:80].rstrip(" .-")


def markdown_bullets(items: list[str] | None) -> str:
    """Convert a list of values into Markdown bullets."""
    cleaned_items = [
        " ".join(item.strip().split())
        for item in (items or [])
        if item and item.strip()
    ]

    if not cleaned_items:
        return "- Not documented"

    return "\n".join(f"- {item}" for item in cleaned_items)


def markdown_numbered(items: list[str] | None) -> str:
    """Convert a list of values into a numbered Markdown list."""
    cleaned_items = [
        " ".join(item.strip().split())
        for item in (items or [])
        if item and item.strip()
    ]

    if not cleaned_items:
        return "1. Not documented"

    return "\n".join(
        f"{index}. {item}"
        for index, item in enumerate(cleaned_items, start=1)
    )


def next_available_session_path(
    inbox_path: Path,
    base_filename: str,
) -> Path:
    """Return a new filename without overwriting an existing session."""
    candidate = inbox_path / f"{base_filename}.md"

    if not candidate.exists():
        return candidate

    for number in range(2, 1000):
        candidate = inbox_path / f"{base_filename} ({number}).md"

        if not candidate.exists():
            return candidate

    raise RuntimeError(
        "Could not generate a unique session-draft filename."
    )


def save_session_draft(
    project: str,
    source: Literal[
        "ChatGPT",
        "Claude Desktop",
        "Claude Code",
        "Codex",
        "Manual",
    ],
    session_goal: str,
    work_completed: list[str] | None = None,
    decisions_proposed: list[str] | None = None,
    tests_or_observations: list[str] | None = None,
    problems_and_risks: list[str] | None = None,
    files_or_systems_affected: list[str] | None = None,
    open_questions: list[str] | None = None,
    next_actions: list[str] | None = None,
    related_git_repository: str | None = None,
    related_branch: str | None = None,
    related_commit: str | None = None,
) -> dict[str, Any]:
    """
    Save a new, unreviewed session draft in Sessions/Inbox.

    This tool never edits permanent project notes and never overwrites an
    existing session file. All proposed decisions remain pending review.
    """
    settings = load_settings()
    vault_path = Path(settings["vault_path"])
    project_path = resolve_project_folder(project)

    inbox_path = (
        vault_path / settings["sessions_inbox"]
    ).resolve()

    if not inbox_path.exists():
        raise FileNotFoundError(
            f"Sessions inbox was not found: {inbox_path}"
        )

    if not inbox_path.is_dir():
        raise NotADirectoryError(
            f"Sessions inbox is not a directory: {inbox_path}"
        )

    project_name = project_path.name
    clean_goal = clean_single_line(session_goal, "Session goal")
    now = datetime.now().astimezone()

    filename_date = now.strftime("%Y-%m-%d")
    metadata_datetime = now.isoformat(timespec="minutes")

    base_filename = (
        f"{filename_date} "
        f"{safe_filename_part(project_name)} "
        f"{safe_filename_part(source)}"
    )

    output_path = next_available_session_path(
        inbox_path,
        base_filename,
    )

    repository = (
        related_git_repository.strip()
        if related_git_repository
        else "Not documented"
    )
    branch = (
        related_branch.strip()
        if related_branch
        else "Not documented"
    )
    commit = (
        related_commit.strip()
        if related_commit
        else "Not documented"
    )

    content = f"""# Session Draft — {project_name}

## Session Metadata

- **Date:** {metadata_datetime}
- **Source:** {source}
- **Project:** {project_name}
- **Session status:** Inbox
- **Related Git repository:** {repository}
- **Related branch:** {branch}
- **Related commit:** {commit}

## Session Goal

{clean_goal}

## Work Completed

{markdown_bullets(work_completed)}

## Decisions Proposed

These decisions are proposals only and are not accepted project knowledge
until reviewed by the user.

{markdown_bullets(decisions_proposed)}

## Tests or Observations

Only tests actually performed or observations actually made should appear here.

{markdown_bullets(tests_or_observations)}

## Problems and Risks

{markdown_bullets(problems_and_risks)}

## Files or Systems Affected

{markdown_bullets(files_or_systems_affected)}

## Open Questions

{markdown_bullets(open_questions)}

## Next Actions

{markdown_numbered(next_actions)}

## Candidate Project Updates

- Project Overview: To be reviewed
- Requirements: To be reviewed
- Design Decisions: To be reviewed
- Bill of Materials: To be reviewed
- Test Log: To be reviewed
- Session Handoff: To be reviewed
- Optional technical notes: To be reviewed

## Review Status

- **Reviewed by user:** No
- **Accepted into project knowledge:** No
- **Processed date:** Not processed
- **Archive location:** Not archived
"""

    try:
        with output_path.open(
            mode="x",
            encoding="utf-8",
            newline="\n",
        ) as session_file:
            session_file.write(content)
    except FileExistsError as exc:
        raise RuntimeError(
            f"Session file unexpectedly already exists: {output_path}"
        ) from exc

    return {
        "status": "created",
        "project": project_name,
        "source": source,
        "path": str(output_path),
        "filename": output_path.name,
        "permanent_project_files_modified": False,
        "review_required": True,
    }

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_latest_handoff(project: str) -> dict[str, Any]:
    """Return the current Session Handoff note for a named project."""
    project_path = resolve_project_folder(project)
    handoff_path = project_path / "Session Handoff.md"

    if not handoff_path.exists():
        raise FileNotFoundError(
            f"Session Handoff.md was not found for: {project}"
        )

    if not handoff_path.is_file():
        raise FileNotFoundError(
            f"Session Handoff path is not a file: {handoff_path}"
        )

    return {
        "project": project_path.name,
        "path": str(handoff_path),
        "content": handoff_path.read_text(encoding="utf-8"),
    }

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_open_decisions(project: str) -> dict[str, Any]:
    """Return unresolved Open or Proposed design decisions for a project."""
    project_path = resolve_project_folder(project)
    decisions_path = project_path / "Design Decisions.md"

    if not decisions_path.exists():
        raise FileNotFoundError(
            f"Design Decisions.md was not found for: {project}"
        )

    if not decisions_path.is_file():
        raise FileNotFoundError(
            f"Design Decisions path is not a file: {decisions_path}"
        )

    content = decisions_path.read_text(encoding="utf-8")
    decisions = extract_open_decisions(content)

    return {
        "project": project_path.name,
        "path": str(decisions_path),
        "count": len(decisions),
        "open_decisions": decisions,
    }

def extract_handoff_section(content: str, heading: str) -> str | None:
    """Return the content beneath a Markdown H2 heading."""
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)

    if not match:
        return None

    section = match.group(1).strip()
    return section or None


def build_imported_note(
    title: str,
    source_filename: str,
    sections: list[tuple[str, str | None]],
) -> str:
    """Build a project note only from sections present in the handoff."""
    output = [
        f"# {title}",
        "",
        f"> Imported from `{source_filename}`.",
        "> Review this note before treating it as accepted project knowledge.",
        "",
    ]

    found_content = False

    for heading, section_content in sections:
        if not section_content:
            continue

        found_content = True
        output.extend(
            [
                f"## {heading}",
                "",
                section_content,
                "",
            ]
        )

    if not found_content:
        output.extend(
            [
                "## Import Result",
                "",
                "No matching source sections were found in the handoff.",
                "",
            ]
        )

    output.extend(
        [
            "## Review Status",
            "",
            "- **Reviewed by user:** No",
            "- **Accepted into project knowledge:** No",
            "",
        ]
    )

    return "\n".join(output)


@mcp.tool()
def import_project_handoff(
    project: str,
    import_filename: str,
) -> dict[str, Any]:
    """
    Import one TXT or Markdown handoff from Imports into an existing project.

    Creates only missing project notes and never overwrites existing files.
    Source content is copied and reorganized without inventing missing details.
    """
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    imports_path = (vault_path / "Imports").resolve()
    project_path = resolve_project_folder(project)

    if not imports_path.exists() or not imports_path.is_dir():
        raise FileNotFoundError(
            f"Imports folder was not found: {imports_path}"
        )

    clean_filename = import_filename.strip()

    if not clean_filename:
        raise ValueError("Import filename cannot be empty.")

    source_path = (imports_path / clean_filename).resolve()

    if source_path.parent != imports_path:
        raise ValueError(
            "Import file must be directly inside the Imports folder."
        )

    if source_path.suffix.casefold() not in {".txt", ".md"}:
        raise ValueError(
            "Import file must have a .txt or .md extension."
        )

    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(
            f"Import file was not found: {source_path}"
        )

    source_content = source_path.read_text(encoding="utf-8")

    sections = {
        heading: extract_handoff_section(source_content, heading)
        for heading in [
            "Project Objective",
            "Current Architecture",
            "Current Windows Paths",
            "Settings Configuration",
            "Implemented MCP Tools",
            "Verified Test Project",
            "Session Draft Safety Model",
            "Claude Desktop Setup",
            "Streamable HTTP Setup",
            "Cloudflare Setup",
            "Cloudflare Host Header Fix",
            "Cloudflare Access Security",
            "Current Security State",
            "Windows Automation Files",
            "Current Known Issue",
            "Current Working State",
            "Remaining Work",
            "Open Questions",
            "Important Safety and Operational Rules",
            "Immediate Next Action",
        ]
    }

    note_definitions = {
        "Project Overview.md": build_imported_note(
            f"{project_path.name} — Project Overview",
            source_path.name,
            [
                ("Objective", sections["Project Objective"]),
                ("Current Architecture", sections["Current Architecture"]),
                ("Current Working State", sections["Current Working State"]),
                ("Remaining Work", sections["Remaining Work"]),
                ("Open Questions", sections["Open Questions"]),
            ],
        ),
        "Requirements.md": build_imported_note(
            f"{project_path.name} — Requirements",
            source_path.name,
            [
                ("Project Objective", sections["Project Objective"]),
                (
                    "Safety and Operational Requirements",
                    sections["Important Safety and Operational Rules"],
                ),
                ("Open Requirements", sections["Open Questions"]),
            ],
        ),
        "Session Handoff.md": build_imported_note(
            f"{project_path.name} — Session Handoff",
            source_path.name,
            [
                ("Current Working State", sections["Current Working State"]),
                ("Current Known Issue", sections["Current Known Issue"]),
                ("Remaining Work", sections["Remaining Work"]),
                ("Open Questions", sections["Open Questions"]),
                ("Next Action", sections["Immediate Next Action"]),
            ],
        ),
        "Test Log.md": build_imported_note(
            f"{project_path.name} — Test Log",
            source_path.name,
            [
                ("Verified Test Project", sections["Verified Test Project"]),
                (
                    "Session Draft Safety Verification",
                    sections["Session Draft Safety Model"],
                ),
                (
                    "Cloudflare Host Header Test",
                    sections["Cloudflare Host Header Fix"],
                ),
                ("Known Connector Issue", sections["Current Known Issue"]),
            ],
        ),
        "Architecture.md": build_imported_note(
            f"{project_path.name} — Architecture",
            source_path.name,
            [
                ("System Architecture", sections["Current Architecture"]),
                ("Implemented MCP Tools", sections["Implemented MCP Tools"]),
                ("Streamable HTTP", sections["Streamable HTTP Setup"]),
                ("Claude Desktop", sections["Claude Desktop Setup"]),
            ],
        ),
        "Deployment.md": build_imported_note(
            f"{project_path.name} — Deployment",
            source_path.name,
            [
                ("Windows Paths", sections["Current Windows Paths"]),
                ("Settings", sections["Settings Configuration"]),
                ("Cloudflare Tunnel", sections["Cloudflare Setup"]),
                ("Windows Automation", sections["Windows Automation Files"]),
                ("Remaining Deployment Work", sections["Remaining Work"]),
            ],
        ),
        "Security.md": build_imported_note(
            f"{project_path.name} — Security",
            source_path.name,
            [
                ("Cloudflare Access", sections["Cloudflare Access Security"]),
                ("Current Security State", sections["Current Security State"]),
                (
                    "Safety and Operational Rules",
                    sections["Important Safety and Operational Rules"],
                ),
            ],
        ),
    }

    created: list[str] = []
    skipped_existing: list[str] = []

    for filename, note_content in note_definitions.items():
        output_path = project_path / filename

        if output_path.exists():
            skipped_existing.append(filename)
            continue

        with output_path.open(
            mode="x",
            encoding="utf-8",
            newline="\n",
        ) as output_file:
            output_file.write(note_content)

        created.append(filename)

    return {
        "status": "completed",
        "project": project_path.name,
        "source_import": str(source_path),
        "created": created,
        "skipped_existing": skipped_existing,
        "files_overwritten": False,
        "review_required": True,
    }

@mcp.tool()
def save_general_session_draft(
    topic: str,
    source: Literal[
        "ChatGPT",
        "Claude Desktop",
        "Claude Code",
        "Codex",
        "Manual",
    ],
    discussion_summary: list[str] | None = None,
    conclusions_reached: list[str] | None = None,
    decisions_proposed: list[str] | None = None,
    useful_information: list[str] | None = None,
    open_questions: list[str] | None = None,
    possible_project: str | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    """
    Save a non-project conversation as an unreviewed session draft.

    The draft is written only to Sessions/Inbox. It does not create a
    project or write directly into accepted General Memory.
    """
    settings = load_settings()
    vault_path = Path(settings["vault_path"])
    inbox_path = (
        vault_path / settings["sessions_inbox"]
    ).resolve()

    if not inbox_path.exists() or not inbox_path.is_dir():
        raise FileNotFoundError(
            f"Sessions inbox was not found: {inbox_path}"
        )

    clean_topic = clean_single_line(topic, "Topic")
    now = datetime.now().astimezone()

    filename_date = now.strftime("%Y-%m-%d")
    metadata_datetime = now.isoformat(timespec="minutes")

    base_filename = (
        f"{filename_date} General "
        f"{safe_filename_part(clean_topic)} "
        f"{safe_filename_part(source)}"
    )

    output_path = next_available_session_path(
        inbox_path,
        base_filename,
    )

    project_candidate = (
        possible_project.strip()
        if possible_project and possible_project.strip()
        else "None"
    )

    content = f"""# General Session Draft — {clean_topic}

## Session Metadata

- **Date:** {metadata_datetime}
- **Source:** {source}
- **Session type:** General
- **Project:** None
- **Topic:** {clean_topic}
- **Session status:** Inbox

## Discussion Summary

{markdown_bullets(discussion_summary)}

## Conclusions Reached

{markdown_bullets(conclusions_reached)}

## Decisions Proposed

These decisions are proposals only and are not accepted memory until
reviewed by the user.

{markdown_bullets(decisions_proposed)}

## Useful Information

{markdown_bullets(useful_information)}

## Open Questions

{markdown_bullets(open_questions)}

## Possible Future Project

- {project_candidate}

## Next Actions

{markdown_numbered(next_actions)}

## Possible Review Outcomes

- Promote accepted information to General Memory
- Create a new project from the approved session
- Add information to an existing project
- Archive without promotion

## Review Status

- **Reviewed by user:** No
- **Accepted as general memory:** No
- **Promoted to project:** No
- **Processed date:** Not processed
- **Archive location:** Not archived
"""

    with output_path.open(
        mode="x",
        encoding="utf-8",
        newline="\n",
    ) as session_file:
        session_file.write(content)

    return {
        "status": "created",
        "session_type": "General",
        "topic": clean_topic,
        "source": source,
        "path": str(output_path),
        "filename": output_path.name,
        "project_created": False,
        "general_memory_modified": False,
        "review_required": True,
    }

def resolve_session_file(session_filename: str) -> Path:
    """Resolve an exact session filename from Inbox or Active."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()

    clean_filename = session_filename.strip()

    if not clean_filename:
        raise ValueError("Session filename cannot be empty.")

    if Path(clean_filename).name != clean_filename:
        raise ValueError("Use only the session filename, not a path.")

    if Path(clean_filename).suffix.casefold() != ".md":
        raise ValueError("Session filename must end with .md.")

    allowed_folders = [
        (vault_path / settings["sessions_inbox"]).resolve(),
        (vault_path / settings["sessions_active"]).resolve(),
    ]

    matches = [
        folder / clean_filename
        for folder in allowed_folders
        if (folder / clean_filename).is_file()
    ]

    if not matches:
        raise FileNotFoundError(
            f"Session was not found in Inbox or Active: {clean_filename}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            f"Session filename exists in more than one folder: {clean_filename}"
        )

    return matches[0]


def session_section(content: str, heading: str) -> str:
    """Read an H2 session section or return Not documented."""
    extracted = extract_handoff_section(content, heading)
    return extracted or "Not documented"


@mcp.tool(annotations=READ_ONLY_TOOL)
def list_project_templates() -> dict[str, Any]:
    """List editable project templates and their supported placeholders."""
    templates_path = project_templates_path()
    templates = []

    for filename in PROJECT_TEMPLATE_FILENAMES:
        template_path = templates_path / filename
        content = template_path.read_text(encoding="utf-8")
        templates.append(
            {
                "template_name": filename,
                "path": str(template_path),
                "placeholders": validate_project_template(
                    filename,
                    content,
                ),
                "required_headings": list(
                    PROJECT_TEMPLATE_REQUIREMENTS[filename]["headings"]
                ),
                "required_placeholders": list(
                    PROJECT_TEMPLATE_REQUIREMENTS[filename]["placeholders"]
                ),
                "draft_exists": (
                    templates_path / ".drafts" / filename
                ).is_file(),
            }
        )

    return {
        "templates_folder": str(templates_path),
        "count": len(templates),
        "templates": templates,
        "supported_placeholders": sorted(PROJECT_TEMPLATE_FIELDS),
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_project_template(template_name: str) -> dict[str, Any]:
    """Read one editable project template and any pending draft."""
    template_path = resolve_project_template(template_name)
    content = template_path.read_text(encoding="utf-8")
    draft_path = template_path.parent / ".drafts" / template_path.name
    draft_content = (
        draft_path.read_text(encoding="utf-8")
        if draft_path.is_file()
        else None
    )
    draft_valid: bool | None = None
    draft_validation_error: str | None = None

    if draft_content is not None:
        try:
            validate_project_template(template_path.name, draft_content)
            draft_valid = True
        except ValueError as exc:
            draft_valid = False
            draft_validation_error = str(exc)

    return {
        "template_name": template_path.name,
        "path": str(template_path),
        "content": content,
        "placeholders": validate_project_template(
            template_path.name,
            content,
        ),
        "required_headings": list(
            PROJECT_TEMPLATE_REQUIREMENTS[template_path.name]["headings"]
        ),
        "required_placeholders": list(
            PROJECT_TEMPLATE_REQUIREMENTS[
                template_path.name
            ]["placeholders"]
        ),
        "draft_path": str(draft_path) if draft_path.is_file() else None,
        "draft_content": draft_content,
        "draft_valid": draft_valid,
        "draft_validation_error": draft_validation_error,
    }


@mcp.tool()
def save_project_template_draft(
    template_name: str,
    content: str,
) -> dict[str, Any]:
    """
    Save a proposed project-template change for user review.

    This never changes the active template. Use
    apply_project_template_draft only after explicit user approval.
    """
    template_path = resolve_project_template(template_name)
    placeholders = validate_project_template(template_path.name, content)
    drafts_path = template_path.parent / ".drafts"
    drafts_path.mkdir(exist_ok=True)
    draft_path = drafts_path / template_path.name
    draft_path.write_text(
        content.rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )

    return {
        "status": "draft_saved",
        "template_name": template_path.name,
        "draft_path": str(draft_path),
        "placeholders": placeholders,
        "active_template_changed": False,
        "approval_required": True,
    }


@mcp.tool()
def apply_project_template_draft(
    template_name: str,
    approved: bool = False,
) -> dict[str, Any]:
    """
    Apply an approved project-template draft and archive the old version.

    Set approved=true only after the user explicitly approves the pending
    draft. Existing projects are not modified.
    """
    if not approved:
        raise PermissionError(
            "Explicit user approval is required to apply a template draft."
        )

    template_path = resolve_project_template(template_name)
    draft_path = template_path.parent / ".drafts" / template_path.name

    if not draft_path.is_file():
        raise FileNotFoundError(
            f"No pending draft exists for: {template_path.name}"
        )

    draft_content = draft_path.read_text(encoding="utf-8")
    placeholders = validate_project_template(
        template_path.name,
        draft_content,
    )
    archive_path = template_path.parent / ".archive"
    archive_path.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = archive_path / f"{timestamp}--{template_path.name}"
    backup_path.write_text(
        template_path.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )

    template_path.write_text(
        draft_content.rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    draft_path.unlink()

    return {
        "status": "applied",
        "template_name": template_path.name,
        "path": str(template_path),
        "backup_path": str(backup_path),
        "placeholders": placeholders,
        "existing_projects_changed": False,
    }


def normalize_template_pack(template_pack: str) -> str:
    """Return one supported template-pack key."""
    clean_pack = clean_single_line(template_pack, "Template pack")
    if clean_pack not in PROJECT_TEMPLATE_PACKS:
        raise ValueError(
            "Unknown project template pack. Expected one of: "
            + ", ".join(PROJECT_TEMPLATE_PACKS)
        )
    return clean_pack


def selected_project_template_files(
    template_packs: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Resolve core plus explicitly selected optional template packs."""
    selected_packs = ["core"]
    for template_pack in template_packs or []:
        clean_pack = normalize_template_pack(template_pack)
        if clean_pack not in selected_packs:
            selected_packs.append(clean_pack)

    selected_files = list(
        dict.fromkeys(
            filename
            for pack in selected_packs
            for filename in PROJECT_TEMPLATE_PACKS[pack]
        )
    )
    return selected_packs, selected_files


def existing_project_template_values(project_name: str) -> dict[str, str]:
    """Return honest placeholders for adding templates to an existing project."""
    return {
        "project_name": project_name,
        "source_session": "Added to existing project from an approved template pack",
        "discussion": "Not documented",
        "conclusions": "Not documented",
        "decisions": "Not documented",
        "useful_information": "Not documented",
        "open_questions": "Not documented",
        "next_actions": "Not documented",
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def list_project_template_packs() -> dict[str, Any]:
    """List core and optional project-note packs without changing projects."""
    return {
        "count": len(PROJECT_TEMPLATE_PACKS),
        "packs": [
            {
                "pack": pack,
                "required": pack == "core",
                "templates": list(filenames),
            }
            for pack, filenames in PROJECT_TEMPLATE_PACKS.items()
        ],
        "application_policy": (
            "Packs create missing notes only and never overwrite existing notes."
        ),
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def preview_project_template_pack(
    project: str,
    template_pack: str,
) -> dict[str, Any]:
    """Preview which notes one template pack would add to a project."""
    project_path = resolve_project_folder(project)
    clean_pack = normalize_template_pack(template_pack)
    filenames = PROJECT_TEMPLATE_PACKS[clean_pack]
    existing = [name for name in filenames if (project_path / name).exists()]
    missing = [name for name in filenames if not (project_path / name).exists()]
    return {
        "status": "preview",
        "project": project_path.name,
        "template_pack": clean_pack,
        "would_create": missing,
        "would_skip_existing": existing,
        "files_overwritten": False,
        "approval_required_to_apply": True,
    }


@mcp.tool()
def apply_project_template_pack(
    project: str,
    template_pack: str,
    approved: bool = False,
) -> dict[str, Any]:
    """Add missing notes from an approved pack without overwriting files."""
    if not approved:
        raise PermissionError(
            "Explicit user approval is required to apply a template pack."
        )

    project_path = resolve_project_folder(project)
    clean_pack = normalize_template_pack(template_pack)
    templates_path = project_templates_path()
    values = existing_project_template_values(project_path.name)
    created: list[str] = []
    skipped: list[str] = []
    planned: list[tuple[Path, str]] = []

    for filename in PROJECT_TEMPLATE_PACKS[clean_pack]:
        output_path = project_path / filename
        if output_path.exists():
            skipped.append(filename)
            continue
        content = render_project_template(
            filename,
            (templates_path / filename).read_text(encoding="utf-8"),
            values,
        )
        planned.append((output_path, content))

    try:
        for output_path, content in planned:
            with output_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            created.append(output_path.name)
    except Exception:
        for filename in created:
            created_path = project_path / filename
            if created_path.is_file():
                created_path.unlink()
        raise

    return {
        "status": "applied",
        "project": project_path.name,
        "template_pack": clean_pack,
        "created_files": created,
        "skipped_existing_files": skipped,
        "files_overwritten": False,
    }


@mcp.tool(annotations=READ_ONLY_TOOL)
def list_project_notes(project: str) -> dict[str, Any]:
    """List visible Markdown notes in one project without reading their bodies."""
    project_path = resolve_project_folder(project)
    notes = [
        {
            "filename": path.name,
            "relative_path": path.relative_to(projects_root_path()).as_posix(),
            "size_bytes": path.stat().st_size,
            "modified": datetime.fromtimestamp(
                path.stat().st_mtime
            ).astimezone().isoformat(timespec="seconds"),
        }
        for path in sorted(project_path.glob("*.md"), key=lambda item: item.name.casefold())
        if path.is_file() and not path.name.startswith(".")
    ]
    return {
        "project": project_path.name,
        "count": len(notes),
        "notes": notes,
    }


def normalize_reorganization_id(reorganization_id: str) -> str:
    """Validate one opaque reorganization draft identifier."""
    clean_id = clean_single_line(reorganization_id, "Reorganization ID")
    if not re.fullmatch(r"[0-9a-f]{32}", clean_id):
        raise ValueError("Invalid reorganization ID.")
    return clean_id


def normalize_reorganization_notes(
    project_path: Path,
    notes: dict[str, str],
) -> list[dict[str, Any]]:
    """Validate complete replacement bodies for existing root project notes."""
    if not isinstance(notes, dict) or not notes:
        raise ValueError("At least one project note replacement is required.")
    if len(notes) > 30:
        raise ValueError("A reorganization may contain at most 30 notes.")

    normalized: list[dict[str, Any]] = []
    total_size = 0
    for raw_filename, content in notes.items():
        filename = clean_single_line(raw_filename, "Project note filename")
        candidate = Path(filename)
        if (
            candidate.name != filename
            or filename.startswith(".")
            or candidate.suffix.casefold() != ".md"
        ):
            raise ValueError(
                "Reorganization notes must be visible Markdown files in the project root."
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Replacement note cannot be empty: {filename}")
        final_content = content.rstrip() + "\n"
        size_bytes = len(final_content.encode("utf-8"))
        if size_bytes > MAX_GENERIC_PROJECT_NOTE_SIZE:
            raise ValueError(f"Replacement note is larger than 1 MB: {filename}")
        total_size += size_bytes
        note_path = project_path / filename
        if not note_path.is_file():
            raise FileNotFoundError(
                f"Reorganization only replaces existing notes: {filename}"
            )
        original = note_path.read_text(encoding="utf-8")
        normalized.append(
            {
                "filename": filename,
                "content": final_content,
                "original_sha256": hashlib.sha256(
                    original.encode("utf-8")
                ).hexdigest(),
                "original_size_bytes": len(original.encode("utf-8")),
                "replacement_size_bytes": size_bytes,
            }
        )

    if total_size > 5 * MAX_GENERIC_PROJECT_NOTE_SIZE:
        raise ValueError("Reorganization draft is larger than 5 MB.")
    return normalized


@mcp.tool()
def stage_project_reorganization(
    project: str,
    notes: dict[str, str],
    description: str,
) -> dict[str, Any]:
    """Stage full replacements for review without changing accepted notes."""
    project_path = resolve_project_folder(project)
    clean_description = clean_single_line(description, "Description")
    normalized = normalize_reorganization_notes(project_path, notes)
    reorganization_id = uuid4().hex
    drafts_path = project_path / ".workshop-reorganization-drafts"
    drafts_path.mkdir(exist_ok=True)
    draft_path = drafts_path / f"{reorganization_id}.json"
    payload = {
        "schema_version": 1,
        "reorganization_id": reorganization_id,
        "project": project_path.name,
        "description": clean_description,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notes": normalized,
    }
    serialized_payload = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    draft_path.write_text(
        serialized_payload,
        encoding="utf-8",
        newline="\n",
    )
    return {
        "status": "staged",
        "reorganization_id": reorganization_id,
        "project": project_path.name,
        "description": clean_description,
        "draft_sha256": hashlib.sha256(
            serialized_payload.encode("utf-8")
        ).hexdigest(),
        "notes": [
            {
                "filename": item["filename"],
                "original_size_bytes": item["original_size_bytes"],
                "replacement_size_bytes": item["replacement_size_bytes"],
            }
            for item in normalized
        ],
        "accepted_notes_changed": False,
        "approval_required": True,
    }


@mcp.tool()
def apply_project_reorganization(
    project: str,
    reorganization_id: str,
    expected_draft_sha256: str,
    approved: bool = False,
) -> dict[str, Any]:
    """Apply an approved, unchanged reorganization draft with rollback."""
    if not approved:
        raise PermissionError(
            "Explicit user approval is required to reorganize project notes."
        )
    project_path = resolve_project_folder(project)
    clean_id = normalize_reorganization_id(reorganization_id)
    draft_path = (
        project_path / ".workshop-reorganization-drafts" / f"{clean_id}.json"
    )
    if not draft_path.is_file():
        raise FileNotFoundError(f"Reorganization draft was not found: {clean_id}")
    serialized_payload = draft_path.read_text(encoding="utf-8")
    clean_expected_hash = clean_single_line(
        expected_draft_sha256, "Expected draft SHA-256"
    ).casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", clean_expected_hash):
        raise ValueError("Expected draft SHA-256 is invalid.")
    actual_draft_hash = hashlib.sha256(
        serialized_payload.encode("utf-8")
    ).hexdigest()
    if actual_draft_hash != clean_expected_hash:
        raise RuntimeError(
            "Reorganization draft changed after preview; stage it again."
        )
    payload = json.loads(serialized_payload)
    if payload.get("project") != project_path.name:
        raise ValueError("Reorganization draft belongs to a different project.")

    validated: list[tuple[Path, str, str]] = []
    for item in payload.get("notes", []):
        filename = clean_single_line(item.get("filename", ""), "Project note filename")
        note_path = project_path / filename
        if note_path.parent != project_path or not note_path.is_file():
            raise FileNotFoundError(f"Project note changed or disappeared: {filename}")
        original = note_path.read_text(encoding="utf-8")
        current_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
        if current_hash != item.get("original_sha256"):
            raise RuntimeError(
                f"Project note changed after preview; stage it again: {filename}"
            )
        replacement = item.get("content")
        if not isinstance(replacement, str) or not replacement.strip():
            raise ValueError(f"Draft replacement is invalid: {filename}")
        validated.append((note_path, original, replacement.rstrip() + "\n"))

    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    archive_path = project_path / ".archive" / "reorganizations" / timestamp
    archive_path.mkdir(parents=True)
    for note_path, original, _replacement in validated:
        (archive_path / note_path.name).write_text(
            original, encoding="utf-8", newline="\n"
        )

    changed_paths: list[Path] = []
    try:
        for note_path, _original, replacement in validated:
            atomic_write_text(note_path, replacement)
            changed_paths.append(note_path)
    except Exception:
        for note_path, original, _replacement in validated:
            if note_path in changed_paths:
                atomic_write_text(note_path, original)
        raise

    draft_path.unlink()
    return {
        "status": "applied",
        "reorganization_id": clean_id,
        "project": project_path.name,
        "description": payload.get("description"),
        "updated_files": [path.name for path, _old, _new in validated],
        "backup_folder": str(archive_path),
        "rollback_performed": False,
    }


@mcp.tool()
def save_project_image_asset(
    project: str,
    filename: str,
    image_base64: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Save a PNG, JPEG, WebP, or GIF image in a project's assets folder.

    The image must be base64 encoded. Existing assets are protected unless
    overwrite=true is explicitly requested by the user.
    """
    project_path = resolve_project_folder(project)

    if len(image_base64) > (MAX_PROJECT_IMAGE_SIZE * 4 // 3) + 16:
        raise ValueError("Encoded project image is larger than 8 MB.")

    try:
        image_data = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image content is not valid base64.") from exc

    clean_filename = validate_project_image(filename, image_data)
    assets_path = (project_path / "assets").resolve()
    assets_path.mkdir(exist_ok=True)
    image_path = (assets_path / clean_filename).resolve()

    if image_path.parent != assets_path:
        raise ValueError("Invalid image filename or path.")

    if image_path.exists() and not overwrite:
        raise FileExistsError(
            f"Project image already exists: {clean_filename}"
        )

    image_path.write_bytes(image_data)

    return {
        "status": "saved",
        "project": project_path.name,
        "filename": clean_filename,
        "path": str(image_path),
        "size_bytes": len(image_data),
        "overwritten": overwrite,
        "obsidian_embed": f"![[assets/{clean_filename}]]",
    }


@mcp.tool()
def create_project_from_general_session(
    project_name: str,
    session_filename: str,
    archive_source_session: bool = True,
    template_packs: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create a new project from an approved general session.

    Creates a new project folder with core notes and explicitly selected
    optional packs. Refuses to overwrite an existing project. Optionally
    archives the source session after success.
    """
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    projects_path = (
        vault_path / settings["projects_folder"]
    ).resolve()

    clean_project_name = clean_single_line(
        project_name,
        "Project name",
    )

    if safe_filename_part(clean_project_name) != clean_project_name:
        raise ValueError(
            "Project name contains characters that are unsafe for a folder."
        )

    project_path = (projects_path / clean_project_name).resolve()

    if project_path.parent != projects_path:
        raise ValueError("Invalid project name or path.")

    if project_path.exists():
        raise FileExistsError(
            f"Project already exists: {clean_project_name}"
        )

    source_path = resolve_session_file(session_filename)
    source_content = source_path.read_text(encoding="utf-8")

    metadata = session_section(source_content, "Session Metadata")

    if (
        "**Session type:** General" not in metadata
        and "**Session type:** general" not in metadata
    ):
        raise ValueError(
            "The source file is not marked as a General session."
        )

    discussion = session_section(
        source_content,
        "Discussion Summary",
    )
    conclusions = session_section(
        source_content,
        "Conclusions Reached",
    )
    decisions = session_section(
        source_content,
        "Decisions Proposed",
    )
    useful_information = session_section(
        source_content,
        "Useful Information",
    )
    open_questions = session_section(
        source_content,
        "Open Questions",
    )
    next_actions = session_section(
        source_content,
        "Next Actions",
    )

    template_values = {
        "project_name": clean_project_name,
        "source_session": source_path.name,
        "discussion": discussion,
        "conclusions": conclusions,
        "decisions": decisions,
        "useful_information": useful_information,
        "open_questions": open_questions,
        "next_actions": next_actions,
    }
    templates_path = project_templates_path()
    selected_packs, selected_files = selected_project_template_files(
        template_packs
    )
    notes = {
        filename: render_project_template(
            filename,
            (templates_path / filename)
            .read_text(encoding="utf-8")
            .replace("![[assets/project-cover.svg]]\n\n", ""),
            template_values,
        )
        for filename in selected_files
    }

    project_path.mkdir()

    created_files: list[str] = []

    try:
        for filename, content in notes.items():
            output_path = project_path / filename

            with output_path.open(
                mode="x",
                encoding="utf-8",
                newline="\n",
            ) as output_file:
                output_file.write(content)

            created_files.append(filename)

        archived_path: Path | None = None

        if archive_source_session:
            archive_folder = (
                vault_path / settings["sessions_archive"]
            ).resolve()

            archive_folder.mkdir(parents=True, exist_ok=True)
            archived_path = next_available_session_path(
                archive_folder,
                source_path.stem,
            )

            source_path.replace(archived_path)

        return {
            "status": "created",
            "project": clean_project_name,
            "project_folder": str(project_path),
            "created_files": created_files,
            "created_assets": [],
            "templates_folder": str(templates_path),
            "template_packs": selected_packs,
            "source_session": source_path.name,
            "source_session_archived": archive_source_session,
            "archive_path": (
                str(archived_path)
                if archived_path
                else None
            ),
            "files_overwritten": False,
            "review_required": True,
        }

    except Exception:
        for filename in created_files:
            file_path = project_path / filename

            if file_path.exists():
                file_path.unlink()

        if project_path.exists() and not any(project_path.iterdir()):
            project_path.rmdir()

        raise

@mcp.tool(annotations=READ_ONLY_TOOL)
def list_import_files() -> dict[str, Any]:
    """List TXT and Markdown files available in the vault Imports folder."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    imports_path = (vault_path / "Imports").resolve()

    if not imports_path.exists():
        return {
            "status": "ok",
            "imports_folder": str(imports_path),
            "files": [],
            "message": "Imports folder does not exist.",
        }

    files = sorted(
        path.name
        for path in imports_path.iterdir()
        if path.is_file()
        and path.suffix.casefold() in {".txt", ".md"}
    )

    return {
        "status": "ok",
        "imports_folder": str(imports_path),
        "file_count": len(files),
        "files": files,
    }

def normalize_progress_fact(value: str) -> str:
    """Normalize one progress fact for deterministic duplicate detection."""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def clean_progress_items(items: list[str] | None) -> list[str]:
    """Clean and deduplicate one incoming progress list while preserving order."""
    cleaned: list[str] = []
    seen: set[str] = set()

    for item in items or []:
        if not item or not item.strip():
            continue

        value = " ".join(item.strip().split())
        normalized = normalize_progress_fact(value)

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        cleaned.append(value)

    return cleaned


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace one UTF-8 text file in its existing directory."""
    temporary_path = path.with_name(
        f".{path.name}.{uuid4().hex}.tmp"
    )

    try:
        temporary_path.write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def insert_newest_first_progress(content: str, block: str) -> str:
    """Insert one progress block above older blocks while preserving the note."""
    clean_content = content.rstrip()
    clean_block = block.strip()

    if PROGRESS_FEED_MARKER in clean_content:
        marker_end = clean_content.index(PROGRESS_FEED_MARKER) + len(
            PROGRESS_FEED_MARKER
        )
        before = clean_content[:marker_end]
        after = clean_content[marker_end:].lstrip()
        return (
            before
            + "\n\n"
            + clean_block
            + ("\n\n" + after if after else "")
            + "\n"
        )

    title_match = re.search(r"^#\s+.+$", clean_content, flags=re.MULTILINE)
    if title_match:
        insert_at = title_match.end()
        before = clean_content[:insert_at]
        after = clean_content[insert_at:].lstrip()
        return (
            before
            + "\n\n"
            + PROGRESS_FEED_MARKER
            + "\n\n"
            + clean_block
            + ("\n\n" + after if after else "")
            + "\n"
        )

    return (
        PROGRESS_FEED_MARKER
        + "\n\n"
        + clean_block
        + "\n\n"
        + clean_content
        + "\n"
    )


@mcp.tool()
def save_project_progress(
    project: str,
    source: str,
    progress_summary: list[str] | None = None,
    work_completed: list[str] | None = None,
    architecture_updates: list[str] | None = None,
    deployment_updates: list[str] | None = None,
    security_updates: list[str] | None = None,
    requirements_updates: list[str] | None = None,
    decisions_made: list[str] | None = None,
    tests_completed: list[str] | None = None,
    problems_resolved: list[str] | None = None,
    current_status: list[str] | None = None,
    open_questions: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    """
    Compare structured project progress with current memory and merge new facts.

    This is the normal project-memory write path. It does not create an
    approval draft. Existing note history is preserved, duplicate facts are
    skipped, backups are created, writes are atomic, and Session Handoff plus
    Change Log are updated in the same transaction.
    """
    project_path = resolve_project_folder(project)
    project_name = project_path.name
    clean_source = clean_single_line(source, "Source")
    now = datetime.now().astimezone()
    timestamp = now.isoformat(timespec="seconds")
    date_label = now.strftime("%Y-%m-%d")
    checkpoint_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"

    incoming_sections: dict[str, list[str]] = {
        "Progress Summary": clean_progress_items(progress_summary),
        "Work Completed": clean_progress_items(work_completed),
        "Architecture Updates": clean_progress_items(architecture_updates),
        "Deployment Updates": clean_progress_items(deployment_updates),
        "Security Updates": clean_progress_items(security_updates),
        "Requirements Updates": clean_progress_items(requirements_updates),
        "Decisions Made": clean_progress_items(decisions_made),
        "Tests Completed": clean_progress_items(tests_completed),
        "Problems Resolved": clean_progress_items(problems_resolved),
        "Current Status": clean_progress_items(current_status),
        "Open Questions": clean_progress_items(open_questions),
        "Next Actions": clean_progress_items(next_actions),
    }

    if not any(incoming_sections.values()):
        raise ValueError("At least one project-progress item is required.")

    existing_note_paths = sorted(project_path.glob("*.md"))
    existing_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in existing_note_paths
        if path.is_file()
    )
    existing_normalized = normalize_progress_fact(existing_content)

    added_by_section: dict[str, list[str]] = {}
    ignored_duplicates: list[str] = []

    for heading, items in incoming_sections.items():
        added_items: list[str] = []

        for item in items:
            normalized = normalize_progress_fact(item)

            if normalized and normalized in existing_normalized:
                ignored_duplicates.append(item)
                continue

            added_items.append(item)
            existing_normalized += " " + normalized

        if added_items:
            added_by_section[heading] = added_items

    if not added_by_section:
        return {
            "status": "no_changes",
            "project": project_name,
            "checkpoint_id": checkpoint_id,
            "updated_notes": [],
            "added": [],
            "ignored_duplicates": ignored_duplicates,
            "backup_created": False,
            "approval_required": False,
        }

    note_mapping: dict[str, list[str]] = {
        "Project Overview.md": [
            "Progress Summary",
            "Work Completed",
            "Current Status",
            "Problems Resolved",
        ],
        "Architecture.md": ["Architecture Updates"],
        (
            "Deployment and Operations.md"
            if (project_path / "Deployment and Operations.md").exists()
            else "Deployment.md"
        ): ["Deployment Updates"],
        (
            "Security and Permissions.md"
            if (project_path / "Security and Permissions.md").exists()
            else "Security.md"
        ): ["Security Updates"],
        "Requirements.md": ["Requirements Updates"],
        "Design Decisions.md": ["Decisions Made"],
        "Test Log.md": ["Tests Completed"],
        "Session Handoff.md": [
            "Progress Summary",
            "Work Completed",
            "Problems Resolved",
            "Current Status",
            "Open Questions",
            "Next Actions",
        ],
    }

    planned_updates: dict[Path, str] = {}

    for filename, headings in note_mapping.items():
        sections: list[str] = []

        for heading in headings:
            items = added_by_section.get(heading, [])

            if not items:
                continue

            sections.append(
                f"### {heading}\n\n"
                + "\n".join(f"- {item}" for item in items)
            )

        if not sections:
            continue

        note_path = project_path / filename
        marker = f"<!-- workshop-progress:{checkpoint_id} -->"
        block = (
            f"{marker}\n"
            f"## Progress Checkpoint — {date_label}\n\n"
            f"- **Saved:** {timestamp}\n"
            f"- **Source:** {clean_source}\n"
            f"- **Checkpoint ID:** {checkpoint_id}\n\n"
            + "\n\n".join(sections)
            + "\n"
        )

        if note_path.exists():
            current = note_path.read_text(encoding="utf-8")
            planned_updates[note_path] = insert_newest_first_progress(
                current,
                block,
            )
        else:
            title = Path(filename).stem
            planned_updates[note_path] = (
                f"# {project_name} — {title}\n\n"
                f"{PROGRESS_FEED_MARKER}\n\n"
                + block.rstrip()
                + "\n"
            )

    change_log_path = project_path / "Change Log.md"
    changed_note_names = sorted(path.name for path in planned_updates)
    all_added = [
        item
        for items in added_by_section.values()
        for item in items
    ]
    change_log_block = (
        f"<!-- workshop-progress:{checkpoint_id} -->\n"
        f"## {timestamp} — Project Progress Saved\n\n"
        f"- **Source:** {clean_source}\n"
        f"- **Checkpoint ID:** {checkpoint_id}\n"
        f"- **Notes updated:** {', '.join(changed_note_names)}\n"
        f"- **New facts:** {len(all_added)}\n"
        f"- **Duplicates ignored:** {len(ignored_duplicates)}\n\n"
        "### Added Facts\n\n"
        + "\n".join(f"- {item}" for item in all_added)
        + "\n"
    )

    if change_log_path.exists():
        planned_updates[change_log_path] = insert_newest_first_progress(
            change_log_path.read_text(encoding="utf-8"),
            change_log_block,
        )
    else:
        planned_updates[change_log_path] = (
            f"# {project_name} — Change Log\n\n"
            f"{PROGRESS_FEED_MARKER}\n\n"
            + change_log_block.rstrip()
            + "\n"
        )

    backup_root = project_path / ".workshop-memory-backups" / checkpoint_id
    backup_root.mkdir(parents=True, exist_ok=False)
    original_files: dict[Path, str | None] = {}

    try:
        for target_path in planned_updates:
            original_content = (
                target_path.read_text(encoding="utf-8")
                if target_path.exists()
                else None
            )
            original_files[target_path] = original_content

            if original_content is not None:
                backup_path = backup_root / target_path.name
                backup_path.write_text(
                    original_content,
                    encoding="utf-8",
                    newline="\n",
                )

        for target_path, new_content in planned_updates.items():
            atomic_write_text(target_path, new_content)

        return {
            "status": "saved",
            "project": project_name,
            "checkpoint_id": checkpoint_id,
            "updated_notes": sorted(path.name for path in planned_updates),
            "added": all_added,
            "added_by_section": added_by_section,
            "ignored_duplicates": ignored_duplicates,
            "backup_created": True,
            "backup_path": str(backup_root),
            "write_method": "atomic_newest_first",
            "approval_required": False,
        }

    except Exception:
        for target_path, original_content in original_files.items():
            if original_content is None:
                if target_path.exists():
                    target_path.unlink()
            else:
                atomic_write_text(target_path, original_content)
        raise


def save_project_update_draft(
    project: str,
    source: str,
    update_summary: str,
    architecture_updates: list[str] | None = None,
    deployment_updates: list[str] | None = None,
    security_updates: list[str] | None = None,
    requirements_updates: list[str] | None = None,
    decisions_made: list[str] | None = None,
    tests_completed: list[str] | None = None,
    current_status: list[str] | None = None,
    open_questions: list[str] | None = None,
    next_actions: list[str] | None = None,
    source_handoff: str | None = None,
) -> dict[str, Any]:
    """
    Save proposed updates for an existing project as an unreviewed session draft.

    This tool does not edit permanent project notes. Use it when new project
    information must be reviewed before being merged into the project.
    """
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    inbox_path = (
        vault_path / settings["sessions_inbox"]
    ).resolve()

    project_path = resolve_project_folder(project)
    clean_project_name = project_path.name

    clean_source = clean_single_line(source, "Source")
    clean_summary = update_summary.strip()

    if not clean_summary:
        raise ValueError("Update summary cannot be empty.")

    inbox_path.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    filename_stem = safe_filename_part(
        f"{today} {clean_project_name} Project Update"
    )

    output_path = next_available_session_path(
        inbox_path,
        filename_stem,
    )

    def section_items(items: list[str] | None) -> str:
        cleaned = [
            item.strip()
            for item in (items or [])
            if item and item.strip()
        ]

        return markdown_bullets(cleaned) if cleaned else "- Not documented"

    source_handoff_text = (
        f"- `{source_handoff.strip()}`"
        if source_handoff and source_handoff.strip()
        else "- None"
    )

    content = f"""# {clean_project_name} — Project Update Draft

## Session Metadata

- **Session type:** Project Update
- **Project:** {clean_project_name}
- **Source:** {clean_source}
- **Created:** {datetime.now().isoformat(timespec="seconds")}
- **Review status:** Unreviewed
- **Applied to project:** No

## Update Summary

{clean_summary}

## Architecture Updates

{section_items(architecture_updates)}

## Deployment Updates

{section_items(deployment_updates)}

## Security Updates

{section_items(security_updates)}

## Requirements Updates

{section_items(requirements_updates)}

## Decisions Made

{section_items(decisions_made)}

## Tests Completed

{section_items(tests_completed)}

## Current Status

{section_items(current_status)}

## Open Questions

{section_items(open_questions)}

## Next Actions

{section_items(next_actions)}

## Source Handoff

{source_handoff_text}

## Review Instructions

Review this draft before applying it to permanent project notes.

Possible actions:

- approve and apply the update
- edit the draft
- leave it pending
- archive it without applying
"""

    with output_path.open(
        mode="x",
        encoding="utf-8",
        newline="\n",
    ) as output_file:
        output_file.write(content)

    return {
        "status": "saved",
        "project": clean_project_name,
        "draft_file": output_path.name,
        "draft_path": str(output_path),
        "project_files_changed": False,
        "review_required": True,
        "applied_to_project": False,
    }

def resolve_import_file(import_filename: str) -> Path:
    """Resolve an exact TXT or Markdown file from the vault Imports folder."""
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    imports_path = (vault_path / "Imports").resolve()

    clean_filename = import_filename.strip()

    if not clean_filename:
        raise ValueError("Import filename cannot be empty.")

    if Path(clean_filename).name != clean_filename:
        raise ValueError("Use only the import filename, not a path.")

    if Path(clean_filename).suffix.casefold() not in {".txt", ".md"}:
        raise ValueError("Import file must be TXT or Markdown.")

    import_path = (imports_path / clean_filename).resolve()

    if import_path.parent != imports_path:
        raise ValueError("Invalid import filename.")

    if not import_path.is_file():
        raise FileNotFoundError(
            f"Import file was not found: {clean_filename}"
        )

    return import_path


def extract_numbered_handoff_section(
    content: str,
    section_number: int,
) -> str:
    """Extract one numbered handoff section."""
    pattern = re.compile(
        rf"""
        ^\s*{section_number}\.\s+[^\n]+\n
        =+\n
        (?P<body>.*?)
        (?=
            ^\s*{section_number + 1}\.\s+[^\n]+\n
            =+\n
            |
            \Z
        )
        """,
        re.MULTILINE | re.DOTALL | re.VERBOSE,
    )

    match = pattern.search(content)

    if not match:
        return "Not documented"

    body = match.group("body").strip()
    return body or "Not documented"


def save_project_update_draft_from_handoff(
    project: str,
    import_filename: str,
    source: str = "Imported migration handoff",
) -> dict[str, Any]:
    """
    Read a handoff from Imports and create a detailed project-update draft.

    This does not modify permanent project notes. The source handoff is
    preserved in the draft and organized into review sections.
    """
    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()
    inbox_path = (
        vault_path / settings["sessions_inbox"]
    ).resolve()

    project_path = resolve_project_folder(project)
    clean_project_name = project_path.name
    import_path = resolve_import_file(import_filename)

    handoff_content = import_path.read_text(encoding="utf-8")

    architecture = extract_numbered_handoff_section(
        handoff_content,
        1,
    )
    ha_configuration = extract_numbered_handoff_section(
        handoff_content,
        3,
    )
    networking = extract_numbered_handoff_section(
        handoff_content,
        4,
    )
    syncthing = extract_numbered_handoff_section(
        handoff_content,
        5,
    )
    tailscale = extract_numbered_handoff_section(
        handoff_content,
        6,
    )
    cloudflare = extract_numbered_handoff_section(
        handoff_content,
        7,
    )
    functional_status = extract_numbered_handoff_section(
        handoff_content,
        8,
    )
    git_workflow = extract_numbered_handoff_section(
        handoff_content,
        9,
    )
    update_procedure = extract_numbered_handoff_section(
        handoff_content,
        10,
    )
    recommended_updates = extract_numbered_handoff_section(
        handoff_content,
        11,
    )

    inbox_path.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    filename_stem = safe_filename_part(
        f"{today} {clean_project_name} Detailed Project Update"
    )
    output_path = next_available_session_path(
        inbox_path,
        filename_stem,
    )

    content = "\n".join(
        [
            f"# {clean_project_name} — Detailed Project Update Draft",
            "",
            "## Session Metadata",
            "",
            "- **Session type:** Project Update",
            f"- **Project:** {clean_project_name}",
            f'- **Source:** {clean_single_line(source, "Source")}',
            f"- **Source handoff:** `{import_path.name}`",
            f"- **Created:** {datetime.now().isoformat(timespec='seconds')}",
            "- **Review status:** Unreviewed",
            "- **Applied to project:** No",
            "",
            "## Update Summary",
            "",
            "The Workshop Memory MCP service was migrated from the Windows "
            "host to a Raspberry Pi running Home Assistant OS. The Obsidian "
            "vault is synchronized between the Pi and Windows PCs through "
            "Syncthing. Deployment source is stored in GitHub, and the "
            "existing Cloudflare MCP endpoint now routes to the Pi.",
            "",
            "## Architecture Updates",
            "",
            architecture,
            "",
            "## Home Assistant App Configuration",
            "",
            ha_configuration,
            "",
            "## MCP Server Networking Changes",
            "",
            networking,
            "",
            "## Syncthing and Vault Synchronization",
            "",
            syncthing,
            "",
            "## Tailscale Connectivity",
            "",
            tailscale,
            "",
            "## Cloudflare Tunnel Changes",
            "",
            cloudflare,
            "",
            "## Current Functional Status",
            "",
            functional_status,
            "",
            "## Git and Source-Control Procedure",
            "",
            git_workflow,
            "",
            "## Home Assistant Update Procedure",
            "",
            update_procedure,
            "",
            "## Recommended Documentation Updates and Open Tasks",
            "",
            recommended_updates,
            "",
            "## Full Source Handoff",
            "",
            "```text",
            handoff_content,
            "```",
            "",
            "## Review Instructions",
            "",
            "Review this draft before applying it to permanent project notes.",
            "",
            "Suggested target notes:",
            "",
            "- `Project Overview.md`",
            "- `Architecture.md`",
            "- `Deployment.md`",
            "- `Security.md`",
            "- `Requirements.md`",
            "- `Session Handoff.md`",
            "- `Test Log.md`",
            "- `Design Decisions.md`",
            "",
            "No permanent project files have been changed.",
            "",
        ]
    )

    with output_path.open(
        mode="x",
        encoding="utf-8",
        newline="\n",
    ) as output_file:
        output_file.write(content)

    return {
        "status": "saved",
        "project": clean_project_name,
        "source_handoff": import_path.name,
        "draft_file": output_path.name,
        "draft_path": str(output_path),
        "project_files_changed": False,
        "review_required": True,
        "applied_to_project": False,
    }

def meaningful_update_section(content: str, heading: str) -> str | None:
    """Return a useful H2 section, excluding empty placeholder content."""
    value = extract_handoff_section(content, heading)

    if not value:
        return None

    value = value.strip()

    normalized = value.casefold().strip(" \n\r\t-")

    placeholders = {
        "not documented",
        "none",
        "n/a",
        "no updates",
    }

    if normalized in placeholders:
        return None

    return value


def combine_update_sections(
    draft_content: str,
    headings: list[str],
) -> str | None:
    """Combine useful draft sections while preserving their headings."""
    collected: list[str] = []

    for heading in headings:
        value = meaningful_update_section(
            draft_content,
            heading,
        )

        if value:
            collected.append(
                f"### {heading}\n\n{value}"
            )

    if not collected:
        return None

    return "\n\n".join(collected)


def apply_project_update_draft(
    project: str,
    draft_filename: str,
    user_confirmed: bool,
    archive_after_apply: bool = False,
) -> dict[str, Any]:
    """
    Apply an approved project-update draft to an existing project.

    This tool inserts dated update sections above older progress entries. It
    preserves existing note content, requires explicit user confirmation, and
    prevents the same draft from being applied more than once.
    """
    if not user_confirmed:
        raise PermissionError(
            "Explicit user confirmation is required before applying "
            "a project update draft."
        )

    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()

    project_path = resolve_project_folder(project)
    clean_project_name = project_path.name

    draft_path = resolve_session_file(draft_filename)
    draft_content = draft_path.read_text(encoding="utf-8")

    metadata = extract_handoff_section(
        draft_content,
        "Session Metadata",
    )

    if not metadata:
        raise ValueError(
            "The selected session is missing Session Metadata."
        )

    if "**Session type:** Project Update" not in metadata:
        raise ValueError(
            "The selected session is not marked as a Project Update."
        )

    expected_project_line = (
        f"**Project:** {clean_project_name}"
    )

    if expected_project_line not in metadata:
        raise ValueError(
            "The project named in the draft does not match the "
            "selected target project."
        )

    if "**Applied to project:** Yes" in metadata:
        raise FileExistsError(
            "This project update draft has already been applied."
        )

    source_marker = (
        f"<!-- workshop-update:{draft_path.name} -->"
    )

    update_date = datetime.now().strftime("%Y-%m-%d")
    applied_timestamp = datetime.now().isoformat(
        timespec="seconds"
    )

    overview_update = combine_update_sections(
        draft_content,
        [
            "Update Summary",
            "Current Status",
            "Current Functional Status",
        ],
    )

    architecture_update = combine_update_sections(
        draft_content,
        [
            "Architecture Updates",
            "MCP Server Networking Changes",
            "Syncthing and Vault Synchronization",
            "Tailscale Connectivity",
            "Cloudflare Tunnel Changes",
        ],
    )

    deployment_update = combine_update_sections(
        draft_content,
        [
            "Deployment Updates",
            "Home Assistant App Configuration",
            "Git and Source-Control Procedure",
            "Home Assistant Update Procedure",
        ],
    )

    security_update = combine_update_sections(
        draft_content,
        [
            "Security Updates",
            "Tailscale Connectivity",
            "Cloudflare Tunnel Changes",
        ],
    )

    requirements_update = combine_update_sections(
        draft_content,
        [
            "Requirements Updates",
        ],
    )

    decisions_update = combine_update_sections(
        draft_content,
        [
            "Decisions Made",
        ],
    )

    test_update = combine_update_sections(
        draft_content,
        [
            "Tests Completed",
            "Current Functional Status",
        ],
    )

    handoff_update = combine_update_sections(
        draft_content,
        [
            "Update Summary",
            "Current Status",
            "Current Functional Status",
            "Open Questions",
            "Next Actions",
            "Recommended Documentation Updates and Open Tasks",
        ],
    )

    update_plan: dict[str, str] = {}

    def add_planned_update(
        filename: str,
        section_title: str,
        body: str | None,
    ) -> None:
        if not body:
            return

        update_plan[filename] = (
            f"{source_marker}\n"
            f"## Project Update — {update_date}\n\n"
            f"**Source draft:** `{draft_path.name}`  \n"
            f"**Applied:** {applied_timestamp}\n\n"
            f"### {section_title}\n\n"
            f"{body}\n"
        )

    add_planned_update(
        "Project Overview.md",
        "Project Status Update",
        overview_update,
    )

    add_planned_update(
        "Architecture.md",
        "Architecture Update",
        architecture_update,
    )

    add_planned_update(
        (
            "Deployment and Operations.md"
            if (project_path / "Deployment and Operations.md").exists()
            else "Deployment.md"
        ),
        "Deployment Update",
        deployment_update,
    )

    add_planned_update(
        (
            "Security and Permissions.md"
            if (project_path / "Security and Permissions.md").exists()
            else "Security.md"
        ),
        "Security Update",
        security_update,
    )

    add_planned_update(
        "Requirements.md",
        "Requirements Update",
        requirements_update,
    )

    add_planned_update(
        "Design Decisions.md",
        "Decisions Added",
        decisions_update,
    )

    add_planned_update(
        "Test Log.md",
        "Test and Verification Update",
        test_update,
    )

    add_planned_update(
        "Session Handoff.md",
        "Current Handoff Update",
        handoff_update,
    )

    if not update_plan:
        raise ValueError(
            "The draft contains no applicable project-update sections."
        )

    target_paths: dict[str, Path] = {
        filename: project_path / filename
        for filename in update_plan
    }

    # Preflight duplicate check before changing any files.
    for filename, target_path in target_paths.items():
        if not target_path.exists():
            continue

        existing_content = target_path.read_text(
            encoding="utf-8"
        )

        if source_marker in existing_content:
            raise FileExistsError(
                f"The draft has already been applied to {filename}."
            )

    original_files: dict[Path, str | None] = {}

    for target_path in target_paths.values():
        original_files[target_path] = (
            target_path.read_text(encoding="utf-8")
            if target_path.exists()
            else None
        )

    original_draft_content = draft_content
    archived_path: Path | None = None

    try:
        changed_files: list[str] = []
        created_files: list[str] = []

        for filename, appended_content in update_plan.items():
            target_path = target_paths[filename]

            if target_path.exists():
                existing_content = target_path.read_text(
                    encoding="utf-8"
                )

                new_content = insert_newest_first_progress(
                    existing_content,
                    appended_content,
                )
            else:
                note_title = Path(filename).stem

                new_content = (
                    f"# {clean_project_name} — {note_title}\n\n"
                    f"{PROGRESS_FEED_MARKER}\n\n"
                    f"{appended_content.rstrip()}\n"
                )

                created_files.append(filename)

            atomic_write_text(target_path, new_content)

            changed_files.append(filename)

        updated_draft = draft_content.replace(
            "- **Review status:** Unreviewed",
            "- **Review status:** Approved",
            1,
        )

        updated_draft = updated_draft.replace(
            "- **Applied to project:** No",
            "- **Applied to project:** Yes",
            1,
        )

        updated_draft += (
            "\n\n## Application Record\n\n"
            f"- **Applied:** {applied_timestamp}\n"
            f"- **Project:** {clean_project_name}\n"
            "- **Method:** Newest-first project update with preserved history\n"
            f"- **Files changed:** {len(changed_files)}\n"
        )

        draft_path.write_text(
            updated_draft,
            encoding="utf-8",
            newline="\n",
        )

        if archive_after_apply:
            archive_folder = (
                vault_path / settings["sessions_archive"]
            ).resolve()

            archive_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            archived_path = next_available_session_path(
                archive_folder,
                draft_path.stem,
            )

            draft_path.replace(archived_path)

        return {
            "status": "applied",
            "project": clean_project_name,
            "source_draft": draft_path.name,
            "changed_files": changed_files,
            "created_files": created_files,
            "files_overwritten": False,
            "update_method": "newest-first",
            "duplicate_protection": True,
            "draft_marked_applied": True,
            "draft_archived": archive_after_apply,
            "archive_path": (
                str(archived_path)
                if archived_path
                else None
            ),
        }

    except Exception:
        # Restore every project note to its exact original state.
        for target_path, original_content in original_files.items():
            if original_content is None:
                if target_path.exists():
                    target_path.unlink()
            else:
                target_path.write_text(
                    original_content,
                    encoding="utf-8",
                    newline="\n",
                )

        # Restore the draft if it was changed or moved.
        if archived_path and archived_path.exists():
            archived_path.replace(draft_path)

        draft_path.write_text(
            original_draft_content,
            encoding="utf-8",
            newline="\n",
        )

        raise

import json
from uuid import uuid4


@mcp.tool()
def stage_server_update(
    target_file: str,
    find_text: str,
    replacement_text: str,
    reason: str,
) -> dict[str, Any]:
    """
    Stage an exact source-code replacement for review and deployment.

    This tool does not modify the running server or Git repository. It writes
    a deterministic patch request into the synchronized vault.
    """
    allowed_targets = {
        "workshop-memory/src/server.py",
        "workshop-memory/config.yaml",
        "workshop-memory/run.sh",
        "workshop-memory/Dockerfile",
        "workshop-memory/requirements.txt",
    }

    clean_target = target_file.strip().replace("\\", "/")

    if clean_target not in allowed_targets:
        raise ValueError(
            "Target file is not permitted. Allowed targets: "
            + ", ".join(sorted(allowed_targets))
        )

    if not find_text:
        raise ValueError("find_text cannot be empty.")

    if find_text == replacement_text:
        raise ValueError(
            "replacement_text must differ from find_text."
        )

    clean_reason = reason.strip()

    if not clean_reason:
        raise ValueError("A reason for the update is required.")

    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()

    inbox_path = (
        vault_path
        / "Server Updates"
        / "Inbox"
    ).resolve()

    inbox_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    update_id = f"{timestamp}-{uuid4().hex[:8]}"

    output_path = inbox_path / f"{update_id}.json"

    payload = {
        "schema_version": 1,
        "update_id": update_id,
        "created": datetime.now().isoformat(
            timespec="seconds"
        ),
        "status": "staged",
        "user_approved": False,
        "target_file": clean_target,
        "find_text": find_text,
        "replacement_text": replacement_text,
        "reason": clean_reason,
        "deployment": {
            "validate_python": (
                clean_target
                == "workshop-memory/src/server.py"
            ),
            "increment_patch_version": True,
            "commit_and_push": True,
        },
    }

    with output_path.open(
        mode="x",
        encoding="utf-8",
        newline="\n",
    ) as output_file:
        json.dump(
            payload,
            output_file,
            indent=2,
            ensure_ascii=False,
        )
        output_file.write("\n")

    return {
        "status": "staged",
        "update_id": update_id,
        "patch_file": output_path.name,
        "patch_path": str(output_path),
        "target_file": clean_target,
        "server_files_changed": False,
        "git_changes_made": False,
        "review_required": True,
    }


@mcp.tool()
def approve_server_update(
    update_id: str,
    user_confirmed: bool,
) -> dict[str, Any]:
    """
    Approve one staged server-update request.

    This does not modify source code, increment versions, commit, or push.
    It only marks the exact staged JSON request as approved for the separate
    deployment script.
    """
    if not user_confirmed:
        raise PermissionError(
            "Explicit user confirmation is required."
        )

    clean_update_id = clean_single_line(
        update_id,
        "Update ID",
    )

    if not re.fullmatch(
        r"\d{8}-\d{6}-[0-9a-f]{8}",
        clean_update_id,
    ):
        raise ValueError("Invalid update ID format.")

    settings = load_settings()
    vault_path = Path(settings["vault_path"]).resolve()

    inbox_path = (
        vault_path
        / "Server Updates"
        / "Inbox"
    ).resolve()

    patch_path = (
        inbox_path / f"{clean_update_id}.json"
    ).resolve()

    if patch_path.parent != inbox_path:
        raise ValueError("Invalid update path.")

    if not patch_path.is_file():
        raise FileNotFoundError(
            f"Staged server update not found: {clean_update_id}"
        )

    payload = json.loads(
        patch_path.read_text(encoding="utf-8")
    )

    if payload.get("update_id") != clean_update_id:
        raise ValueError(
            "Update ID does not match the staged file."
        )

    current_status = payload.get("status")

    if current_status == "approved":
        return {
            "status": "already_approved",
            "update_id": clean_update_id,
            "patch_file": patch_path.name,
            "server_files_changed": False,
            "git_changes_made": False,
        }

    if current_status != "staged":
        raise ValueError(
            f"Only staged updates can be approved. "
            f"Current status: {current_status}"
        )

    payload["status"] = "approved"
    payload["user_approved"] = True
    payload["approved_at"] = datetime.now().isoformat(
        timespec="seconds"
    )

    patch_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    return {
        "status": "approved",
        "update_id": clean_update_id,
        "patch_file": patch_path.name,
        "target_file": payload.get("target_file"),
        "server_files_changed": False,
        "git_changes_made": False,
        "ready_for_deployment": True,
    }

@mcp.tool()
def apply_server_change(
    target_file: str,
    find_text: str,
    replacement_text: str,
    reason: str,
) -> dict[str, Any]:
    """
    Apply one exact server repository change through the trusted deployment
    agent. The agent validates the change, increments the Home Assistant app
    version, commits it, and pushes it to GitHub.
    """
    agent_url = os.getenv(
        "WORKSHOP_DEPLOY_AGENT_URL",
        "",
    ).strip().rstrip("/")

    agent_token = os.getenv(
        "WORKSHOP_DEPLOY_AGENT_TOKEN",
        "",
    ).strip()

    if not agent_url:
        raise RuntimeError(
            "Deployment-agent URL is not configured."
        )

    if not agent_token:
        raise RuntimeError(
            "Deployment-agent token is not configured."
        )

    clean_target = target_file.strip().replace("\\", "/")
    clean_reason = reason.strip()

    if not find_text:
        raise ValueError("find_text cannot be empty.")

    if find_text == replacement_text:
        raise ValueError(
            "replacement_text must differ from find_text."
        )

    if not clean_reason:
        raise ValueError(
            "A reason for the server change is required."
        )

    payload = {
        "target_file": clean_target,
        "find_text": find_text,
        "replacement_text": replacement_text,
        "reason": clean_reason,
    }

    try:
        response = httpx.post(
            f"{agent_url}/apply-change",
            headers={
                "X-Workshop-Token": agent_token,
            },
            json=payload,
            timeout=60.0,
        )
    except httpx.RequestError as error:
        raise RuntimeError(
            f"Could not reach the deployment agent: {error}"
        ) from error

    try:
        response_data = response.json()
    except ValueError:
        response_data = {
            "detail": response.text,
        }

    if response.status_code >= 400:
        detail = response_data.get(
            "detail",
            response.text,
        )

        raise RuntimeError(
            f"Deployment agent rejected the change: {detail}"
        )

    return {
        "status": response_data.get("status"),
        "target_file": response_data.get("target_file"),
        "previous_version": response_data.get(
            "previous_version"
        ),
        "new_version": response_data.get("new_version"),
        "commit": response_data.get("commit"),
        "commit_message": response_data.get(
            "commit_message"
        ),
        "pushed": response_data.get("pushed"),
        "home_assistant_update_required": (
            response_data.get(
                "home_assistant_update_required"
            )
        ),
    }

@mcp.tool(annotations=READ_ONLY_TOOL)
def check_deploy_agent_status() -> dict[str, Any]:
    """Check the configured deploy agent health endpoint without mutating state."""
    agent_url = os.getenv(
        "WORKSHOP_DEPLOY_AGENT_URL",
        "",
    ).strip().rstrip("/")

    result: dict[str, Any] = {
        "reachable": False,
        "agent_url": agent_url,
        "http_status": None,
        "response_json": None,
        "error": None,
    }

    if not agent_url:
        result["error"] = {
            "type": "configuration_error",
            "message": "WORKSHOP_DEPLOY_AGENT_URL is not configured.",
        }
        return result

    try:
        response = httpx.get(
            f"{agent_url}/health",
            headers={
                "Accept": "application/json",
            },
            timeout=3.0,
        )

        result["http_status"] = response.status_code
        result["reachable"] = response.status_code < 500

        try:
            result["response_json"] = response.json()
        except ValueError:
            result["response_json"] = None

        if response.status_code >= 400:
            result["error"] = {
                "type": "http_error",
                "message": response.text,
            }

        return result
    except httpx.RequestError as exc:
        return {
            **result,
            "reachable": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


if __name__ == "__main__":
    import os

    transport = os.getenv("WORKSHOP_MCP_TRANSPORT", "stdio")

    if transport == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
