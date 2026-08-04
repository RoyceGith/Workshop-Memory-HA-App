from __future__ import annotations
import os
import httpx
import json
from uuid import uuid4
from pathlib import Path
import re
from datetime import datetime
from typing import Any, Literal

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server import MCPServer



PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"

mcp = MCPServer("Workshop Memory MCP")


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


@mcp.tool()
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

@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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

@mcp.tool()
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

@mcp.tool()
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


@mcp.tool()
def create_project_from_general_session(
    project_name: str,
    session_filename: str,
    archive_source_session: bool = True,
) -> dict[str, Any]:
    """
    Create a new project from an approved general session.

    Creates a new project folder and standard notes. Refuses to overwrite an
    existing project. Optionally archives the source session after success.
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

    notes = {
        "Project Overview.md": f"""# {clean_project_name}

## Objective

{conclusions}

## Current Stage

- Initial project creation / definition

## Background

{discussion}

## Current Knowledge

{useful_information}

## Open Questions

{open_questions}

## Next Actions

{next_actions}

## Source Session

- `{source_path.name}`

## Review Status

- **Reviewed by user:** No
- **Accepted into project knowledge:** No
""",
        "Requirements.md": f"""# {clean_project_name} — Requirements

## Project Goal

{conclusions}

## Initial Requirements

{useful_information}

## Open Requirements

{open_questions}

## Constraints

- Not documented

## Acceptance Criteria

- To be defined and reviewed

## Source Session

- `{source_path.name}`

## Review Status

- **Reviewed by user:** No
- **Accepted into project knowledge:** No
""",
        "Design Decisions.md": f"""# {clean_project_name} — Design Decisions

## Proposed Decisions from Source Session

{decisions}

> These are proposals only. Convert accepted items into individual DD records
> after review.

## Review Status

- **Reviewed by user:** No
- **Accepted into project knowledge:** No
""",
        "Session Handoff.md": f"""# {clean_project_name} — Session Handoff

## Current Project Stage

- Initial project creation / definition

## Current Working State

The project was created from the approved general session:

- `{source_path.name}`

## Background

{discussion}

## Conclusions Reached

{conclusions}

## Open Questions

{open_questions}

## Next Actions

{next_actions}

## Review Status

- **Reviewed by user:** No
- **Accepted into project knowledge:** No
""",
        "Test Log.md": f"""# {clean_project_name} — Test Log

## Current Test Status

- No project tests documented yet.

## Source Session

- `{source_path.name}`

## Review Status

- **Reviewed by user:** No
""",
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

@mcp.tool()
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

@mcp.tool()
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


@mcp.tool()
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
    value = extract_handoff_section(content, heading).strip()

    if not value:
        return None

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


@mcp.tool()
def apply_project_update_draft(
    project: str,
    draft_filename: str,
    user_confirmed: bool,
    archive_after_apply: bool = False,
) -> dict[str, Any]:
    """
    Apply an approved project-update draft to an existing project.

    This tool appends dated update sections to project notes. It never replaces
    existing note content. It requires explicit user confirmation and prevents
    the same draft from being applied more than once.
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
            f"\n\n{source_marker}\n"
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
        "Deployment.md",
        "Deployment Update",
        deployment_update,
    )

    add_planned_update(
        "Security.md",
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

                new_content = (
                    existing_content.rstrip()
                    + appended_content
                    + "\n"
                )
            else:
                note_title = Path(filename).stem

                new_content = (
                    f"# {clean_project_name} — {note_title}\n"
                    f"{appended_content}\n"
                )

                created_files.append(filename)

            target_path.write_text(
                new_content,
                encoding="utf-8",
                newline="\n",
            )

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
            "- **Method:** Append-only project update\n"
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
            "update_method": "append-only",
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

if __name__ == "__main__":
    import os

    transport = os.getenv("WORKSHOP_MCP_TRANSPORT", "stdio")

    if transport == "http":
        mcp.run(
            transport="streamable-http",
            host=os.getenv("WORKSHOP_MCP_HOST", "127.0.0.1"),
            port=3001,
            stateless_http=True,
            json_response=True,
        )
    else:
        mcp.run()
