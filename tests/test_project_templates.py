import base64
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "workshop-memory" / "src" / "server.py"


class FakeFastMCP:
    def __init__(self, *args, **kwargs):
        pass

    def tool(self):
        return lambda function: function

    def run(self, *args, **kwargs):
        raise AssertionError("The MCP server must not start during tests.")


def load_server_module():
    mcp_module = types.ModuleType("mcp")
    mcp_server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = FakeFastMCP
    httpx_module = types.ModuleType("httpx")

    original_modules = {
        name: sys.modules.get(name)
        for name in ("mcp", "mcp.server", "mcp.server.fastmcp", "httpx")
    }
    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = mcp_server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module
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
        self.vault = Path(self.temporary_directory.name) / "vault"

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
        self.temporary_directory.cleanup()

    def test_templates_are_seeded_and_drafts_require_approval(self):
        result = self.server.list_project_templates()
        self.assertEqual(result["count"], 5)

        template = self.server.get_project_template("Project Overview.md")
        changed = template["content"].replace(
            "Project objective",
            "Approved project objective",
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
        self.assertIn("![[assets/project-cover.svg]]", overview)
        self.assertNotIn("{{project_name}}", overview)
        self.assertTrue((project_path / "assets/project-cover.svg").is_file())

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


if __name__ == "__main__":
    unittest.main()
