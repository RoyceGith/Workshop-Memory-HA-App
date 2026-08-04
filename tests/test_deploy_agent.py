import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "deploy_agent.py"


def load_agent_module():
    spec = importlib.util.spec_from_file_location(
        "workshop_deploy_agent_test",
        AGENT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DeployAgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = load_agent_module()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary_directory.name)
        self.previous_repo_path = os.environ.get("WORKSHOP_REPO_PATH")
        self.previous_token = os.environ.get("WORKSHOP_DEPLOY_AGENT_TOKEN")
        os.environ["WORKSHOP_REPO_PATH"] = str(self.repo)

        (self.repo / "workshop-memory/src").mkdir(parents=True)
        (self.repo / "workshop-memory").mkdir(exist_ok=True)
        (self.repo / "workshop-memory/config.yaml").write_text(
            'name: Workshop Memory MCP\nversion: "1.2.3"\n',
            encoding="utf-8",
        )
        (self.repo / "workshop-memory/src/server.py").write_text(
            "print('old')\n",
            encoding="utf-8",
        )

    def tearDown(self):
        if self.previous_repo_path is None:
            os.environ.pop("WORKSHOP_REPO_PATH", None)
        else:
            os.environ["WORKSHOP_REPO_PATH"] = self.previous_repo_path

        if self.previous_token is None:
            os.environ.pop("WORKSHOP_DEPLOY_AGENT_TOKEN", None)
        else:
            os.environ["WORKSHOP_DEPLOY_AGENT_TOKEN"] = self.previous_token

        self.temporary_directory.cleanup()

    def test_bump_patch_version(self):
        old_version, new_version = self.agent.bump_patch_version(
            self.repo / "workshop-memory/config.yaml"
        )

        self.assertEqual(old_version, "1.2.3")
        self.assertEqual(new_version, "1.2.4")
        self.assertIn(
            'version: "1.2.4"',
            (self.repo / "workshop-memory/config.yaml").read_text(
                encoding="utf-8"
            ),
        )

    def test_validate_payload_rejects_unknown_target(self):
        with self.assertRaisesRegex(
            self.agent.DeployError,
            "Target file is not permitted",
        ):
            self.agent.validate_payload(
                {
                    "target_file": "../secret.txt",
                    "find_text": "old",
                    "replacement_text": "new",
                    "reason": "test",
                }
            )

    def test_resolve_target_stays_inside_repo(self):
        target = self.agent.resolve_target(
            self.repo,
            "workshop-memory/src/server.py",
        )

        self.assertEqual(
            target,
            (self.repo / "workshop-memory/src/server.py").resolve(),
        )

    def test_deploy_token_rejects_placeholder_and_short_values(self):
        os.environ["WORKSHOP_DEPLOY_AGENT_TOKEN"] = (
            "replace-with-a-long-random-token"
        )

        with self.assertRaisesRegex(
            self.agent.DeployError,
            "non-placeholder",
        ):
            self.agent.deploy_token()

        os.environ["WORKSHOP_DEPLOY_AGENT_TOKEN"] = "too-short"

        with self.assertRaisesRegex(
            self.agent.DeployError,
            "at least 32",
        ):
            self.agent.deploy_token()

        os.environ["WORKSHOP_DEPLOY_AGENT_TOKEN"] = "a" * 32
        self.assertEqual(self.agent.deploy_token(), "a" * 32)


if __name__ == "__main__":
    unittest.main()
