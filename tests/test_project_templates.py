import base64
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "workshop-memory" / "src" / "server.py"


class FakeFastMCP:
    def __init__(self, *args, **kwargs):
        self.tools = {}

    def tool(self, **kwargs):
        def decorator(function):
            self.tools[function.__name__] = kwargs
            return function

        return decorator

    def run(self, *args, **kwargs):
        raise AssertionError("The MCP server must not start during tests.")


def load_server_module():
    mcp_module = types.ModuleType("mcp")
    mcp_server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = FakeFastMCP
    mcp_types_module = types.ModuleType("mcp.types")

    class ToolAnnotations:
        def __init__(self, **kwargs):
            self.values = kwargs

    mcp_types_module.ToolAnnotations = ToolAnnotations
    httpx_module = types.ModuleType("httpx")

    original_modules = {
        name: sys.modules.get(name)
        for name in ("mcp", "mcp.server", "mcp.server.fastmcp", "mcp.types", "httpx")
    }
    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = mcp_server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module
    sys.modules["mcp.types"] = mcp_types_module
    sys.modules["httpx"] = httpx_module

    try:
        spec = importlib.util.spec_from_file_location(
            "workshop_memory_server_test",
            SERVER_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class ProjectTemplateTests(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.vault = self.temp_path / "vault"
        self.code_repo = self.temp_path / "repo"
        self.previous_code_repository_path = os.environ.get(
            "WORKSHOP_CODE_REPOSITORY_PATH"
        )
        os.environ["WORKSHOP_CODE_REPOSITORY_PATH"] = str(self.code_repo)

        self.code_repo.mkdir()

        for folder in (
            "Projects",
            "Sessions/Inbox",
            "Sessions/Active",
            "Sessions/Archive",
        ):
            (self.vault / folder).mkdir(parents=True, exist_ok=True)

        settings_path = Path(self.temporary_directory.name) / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "vault_path": str(self.vault),
                    "profile_summary": "Profile/Profile Summary.md",
                    "projects_folder": "Projects",
                    "project_templates_folder": (
                        "Templates/Workshop Memory/Projects"
                    ),
                    "sessions_inbox": "Sessions/Inbox",
                    "sessions_active": "Sessions/Active",
                    "sessions_archive": "Sessions/Archive",
                }
            ),
            encoding="utf-8",
        )
        self.server.SETTINGS_PATH = settings_path

    def tearDown(self):
        if self.previous_code_repository_path is None:
            os.environ.pop("WORKSHOP_CODE_REPOSITORY_PATH", None)
        else:
            os.environ["WORKSHOP_CODE_REPOSITORY_PATH"] = (
                self.previous_code_repository_path
            )

        self.temporary_directory.cleanup()

    def test_templates_are_seeded_and_drafts_require_approval(self):
        result = self.server.list_project_templates()
        self.assertEqual(result["count"], 19)

        template = self.server.get_project_template("Project Overview.md")
        changed = template["content"].replace(
            "Executive snapshot only",
            "Approved executive snapshot",
        )
        draft = self.server.save_project_template_draft(
            "Project Overview.md",
            changed,
        )
        self.assertTrue(draft["approval_required"])

        with self.assertRaises(PermissionError):
            self.server.apply_project_template_draft("Project Overview.md")

        applied = self.server.apply_project_template_draft(
            "Project Overview.md",
            approved=True,
        )
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(Path(applied["backup_path"]).is_file())

    def test_project_creation_renders_templates_and_cover(self):
        session_path = self.vault / "Sessions/Inbox/idea.md"
        session_path.write_text(
            """# General Session

## Session Metadata

- **Session type:** General

## Discussion Summary

- Build a useful workshop tool.

## Conclusions Reached

- Make the status easy to scan.

## Decisions Proposed

- Use local project assets.

## Useful Information

- Obsidian supports Mermaid and callouts.

## Open Questions

- Which project image should be generated next?

## Next Actions

1. Review the generated project.
""",
            encoding="utf-8",
        )

        result = self.server.create_project_from_general_session(
            "Visual Project",
            "idea.md",
            archive_source_session=False,
        )
        project_path = Path(result["project_folder"])
        overview = (project_path / "Project Overview.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("# Visual Project", overview)
        self.assertEqual(result["created_assets"], [])
        self.assertNotIn("![[assets/project-cover.svg]]", overview)
        self.assertNotIn("{{project_name}}", overview)
        self.assertFalse((project_path / "assets").exists())

    def test_project_creation_can_include_optional_template_pack(self):
        session_path = self.vault / "Sessions/Inbox/hardware.md"
        session_path.write_text(
            """# General Session

## Session Metadata

- **Session type:** General

## Discussion Summary

- Build a motor controller.
""",
            encoding="utf-8",
        )

        result = self.server.create_project_from_general_session(
            "Hardware Project",
            "hardware.md",
            archive_source_session=False,
            template_packs=["hardware_mechatronics"],
        )
        project_path = Path(result["project_folder"])

        self.assertEqual(
            result["template_packs"],
            ["core", "hardware_mechatronics"],
        )
        self.assertTrue((project_path / "Bill of Materials.md").is_file())
        self.assertTrue((project_path / "Wiring and Pin Map.md").is_file())
        self.assertFalse((project_path / "Architecture.md").exists())

    def test_template_pack_preview_and_apply_never_overwrite(self):
        project_path = self.vault / "Projects/Existing Hardware"
        project_path.mkdir()
        existing_bom = project_path / "Bill of Materials.md"
        existing_bom.write_text("# Existing BOM\n", encoding="utf-8")

        preview = self.server.preview_project_template_pack(
            "Existing Hardware",
            "hardware_mechatronics",
        )
        self.assertIn("Wiring and Pin Map.md", preview["would_create"])
        self.assertEqual(
            preview["would_skip_existing"],
            ["Bill of Materials.md"],
        )

        with self.assertRaises(PermissionError):
            self.server.apply_project_template_pack(
                "Existing Hardware",
                "hardware_mechatronics",
            )

        applied = self.server.apply_project_template_pack(
            "Existing Hardware",
            "hardware_mechatronics",
            approved=True,
        )
        self.assertEqual(existing_bom.read_text(encoding="utf-8"), "# Existing BOM\n")
        self.assertIn("Wiring and Pin Map.md", applied["created_files"])
        self.assertEqual(applied["skipped_existing_files"], ["Bill of Materials.md"])

    def test_reorganization_requires_approval_backs_up_and_rejects_stale_notes(self):
        project_path = self.vault / "Projects/Mixed Project"
        project_path.mkdir()
        overview_path = project_path / "Project Overview.md"
        overview_path.write_text("# Mixed\n\nOld mixed content.\n", encoding="utf-8")

        staged = self.server.stage_project_reorganization(
            "Mixed Project",
            {"Project Overview.md": "# Mixed\n\nOrganized content."},
            "Separate current state from history",
        )
        self.assertFalse(staged["accepted_notes_changed"])
        self.assertIn("Old mixed content", overview_path.read_text(encoding="utf-8"))

        with self.assertRaises(PermissionError):
            self.server.apply_project_reorganization(
                "Mixed Project",
                staged["reorganization_id"],
                staged["draft_sha256"],
            )

        applied = self.server.apply_project_reorganization(
            "Mixed Project",
            staged["reorganization_id"],
            staged["draft_sha256"],
            approved=True,
        )
        self.assertIn("Organized content", overview_path.read_text(encoding="utf-8"))
        backup_path = Path(applied["backup_folder"]) / "Project Overview.md"
        self.assertIn("Old mixed content", backup_path.read_text(encoding="utf-8"))

        tampered = self.server.stage_project_reorganization(
            "Mixed Project",
            {"Project Overview.md": "# Mixed\n\nTamper target."},
            "Tamper check",
        )
        tampered_path = (
            project_path
            / ".workshop-reorganization-drafts"
            / f"{tampered['reorganization_id']}.json"
        )
        tampered_path.write_text(
            tampered_path.read_text(encoding="utf-8").replace(
                "Tamper target", "Changed draft"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "draft changed after preview"):
            self.server.apply_project_reorganization(
                "Mixed Project",
                tampered["reorganization_id"],
                tampered["draft_sha256"],
                approved=True,
            )

        stale = self.server.stage_project_reorganization(
            "Mixed Project",
            {"Project Overview.md": "# Mixed\n\nSecond organization."},
            "Second pass",
        )
        overview_path.write_text("# Mixed\n\nConcurrent edit.\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "changed after preview"):
            self.server.apply_project_reorganization(
                "Mixed Project",
                stale["reorganization_id"],
                stale["draft_sha256"],
                approved=True,
            )

    def test_generic_project_note_creates_folder_and_supports_safe_updates(self):
        created = self.server.write_project_note(
            "NOTES/HA OS Entities.md",
            "# HA OS Entities\n\n- sensor.workshop_temperature",
        )
        note_path = self.vault / "Projects/NOTES/HA OS Entities.md"

        self.assertEqual(created["status"], "created")
        self.assertEqual(created["created_folders"], ["NOTES"])
        self.assertTrue(note_path.is_file())
        self.assertIn(
            "sensor.workshop_temperature",
            self.server.read_project_note("NOTES/HA OS Entities.md")["content"],
        )

        appended = self.server.write_project_note(
            "NOTES/HA OS Entities.md",
            "- light.workshop",
            mode="append",
        )
        self.assertEqual(appended["status"], "appended")
        self.assertIn("light.workshop", note_path.read_text(encoding="utf-8"))

        replaced = self.server.write_project_note(
            "NOTES/HA OS Entities.md",
            "# Replacement",
            mode="replace",
        )
        self.assertEqual(replaced["status"], "replaced")
        self.assertTrue(Path(replaced["backup_path"]).is_file())

    def test_generic_project_note_rejects_unsafe_paths_and_overwrite(self):
        with self.assertRaisesRegex(ValueError, "stay inside Projects"):
            self.server.write_project_note("../Outside.md", "unsafe")
        with self.assertRaisesRegex(ValueError, "must use the .md extension"):
            self.server.write_project_note("NOTES/entities.txt", "unsafe")
        with self.assertRaises(FileNotFoundError):
            self.server.write_project_note(
                "MISSING/note.md",
                "cannot append",
                mode="append",
            )
        self.assertFalse((self.vault / "Projects/MISSING").exists())

        self.server.write_project_note("NOTES/existing.md", "first")
        with self.assertRaises(FileExistsError):
            self.server.write_project_note("NOTES/existing.md", "second")

    def test_read_tools_publish_annotations_and_note_write_does_not(self):
        for tool_name in (
            "check_server_status",
            "list_projects",
            "get_project_context",
            "read_project_note",
            "list_project_templates",
            "list_project_template_packs",
            "preview_project_template_pack",
            "list_project_notes",
        ):
            annotations = self.server.mcp.tools[tool_name]["annotations"]
            self.assertTrue(annotations.values["readOnlyHint"])

        self.assertNotIn("annotations", self.server.mcp.tools["write_project_note"])

    def test_incomplete_template_drafts_are_rejected(self):
        template = self.server.get_project_template("Project Overview.md")
        missing_section = template["content"].replace(
            "## Open Questions",
            "### Open Questions",
        )

        with self.assertRaisesRegex(
            ValueError,
            "missing required H2 sections: Open Questions",
        ):
            self.server.save_project_template_draft(
                "Project Overview.md",
                missing_section,
            )

        missing_placeholder = template["content"].replace(
            "{{next_actions}}",
            "No actions were preserved.",
        )

        with self.assertRaisesRegex(
            ValueError,
            "missing required placeholders:.*next_actions",
        ):
            self.server.save_project_template_draft(
                "Project Overview.md",
                missing_placeholder,
            )

    def test_existing_incomplete_draft_is_reported_for_correction(self):
        template = self.server.get_project_template("Project Overview.md")
        drafts_path = Path(template["path"]).parent / ".drafts"
        drafts_path.mkdir()
        (drafts_path / "Project Overview.md").write_text(
            "# {{project_name}}\n\n## Objective\n\nPretty but incomplete.\n",
            encoding="utf-8",
        )

        result = self.server.get_project_template("Project Overview.md")

        self.assertFalse(result["draft_valid"])
        self.assertIn(
            "missing required placeholders",
            result["draft_validation_error"],
        )

    def test_image_asset_is_validated_and_saved(self):
        project_path = self.vault / "Projects/Visual Project"
        project_path.mkdir()
        one_pixel_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
            "QVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

        result = self.server.save_project_image_asset(
            "Visual Project",
            "status.png",
            base64.b64encode(one_pixel_png).decode("ascii"),
        )

        self.assertEqual(result["obsidian_embed"], "![[assets/status.png]]")
        self.assertTrue(Path(result["path"]).is_file())

    def test_missing_project_update_sections_are_ignored(self):
        self.assertIsNone(
            self.server.meaningful_update_section(
                "# Draft\n\n## Other Section\n\nUseful content.\n",
                "Update Summary",
            )
        )

        combined = self.server.combine_update_sections(
            "# Draft\n\n## Update Summary\n\nUseful content.\n",
            ["Missing Section", "Update Summary"],
        )

        self.assertEqual(
            combined,
            "### Update Summary\n\nUseful content.",
        )

    def test_project_update_draft_without_metadata_has_clear_error(self):
        project_path = self.vault / "Projects/Workshop Memory MCP"
        project_path.mkdir()
        draft_path = self.vault / "Sessions/Inbox/update.md"
        draft_path.write_text(
            "# Project Update\n\n## Update Summary\n\nUpdated deployment notes.\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "missing Session Metadata",
        ):
            self.server.apply_project_update_draft(
                "Workshop Memory MCP",
                "update.md",
                user_confirmed=True,
            )

    def test_repository_code_tools_read_and_search_safe_files(self):
        source_path = self.code_repo / "workshop-memory/src/server.py"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "def check_server_status():\n    return {'status': 'ok'}\n",
            encoding="utf-8",
        )
        (self.code_repo / "README.md").write_text(
            "# Workshop Memory\n",
            encoding="utf-8",
        )

        listed = self.server.list_repository_files()
        listed_paths = {item["path"] for item in listed["files"]}

        self.assertIn("workshop-memory/src/server.py", listed_paths)
        self.assertIn("README.md", listed_paths)

        read_result = self.server.read_repository_file(
            "workshop-memory/src/server.py"
        )
        self.assertIn("check_server_status", read_result["content"])

        search_result = self.server.search_repository_code(
            "check_server_status"
        )

        self.assertEqual(search_result["count"], 1)
        self.assertEqual(
            search_result["matches"][0]["path"],
            "workshop-memory/src/server.py",
        )

    def test_repository_code_tools_block_secret_paths(self):
        secret_path = self.code_repo / ".env"
        secret_path.write_text(
            "TOKEN=secret\n",
            encoding="utf-8",
        )
        ssh_path = self.code_repo / ".ssh/id_ed25519"
        ssh_path.parent.mkdir()
        ssh_path.write_text(
            "private-key\n",
            encoding="utf-8",
        )

        listed = self.server.list_repository_files()
        listed_paths = {item["path"] for item in listed["files"]}

        self.assertNotIn(".env", listed_paths)
        self.assertNotIn(".ssh/id_ed25519", listed_paths)

        with self.assertRaises(PermissionError):
            self.server.read_repository_file(".env")

        with self.assertRaises(PermissionError):
            self.server.search_repository_code(
                "private-key",
                path_prefix=".ssh",
            )


if __name__ == "__main__":
    unittest.main()
