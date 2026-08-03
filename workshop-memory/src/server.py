from __future__ import annotations

import json
from pathlib import Path
import re
from datetime import datetime
from typing import Any, Literal

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
    settings = load_settings()
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