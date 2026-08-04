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

    def test_deploy_agent_targets_bump_deploy_agent_addon(self):
        (self.repo / "deploy_agent.py").write_text(
            "print('agent')\n",
            encoding="utf-8",
        )
        (self.repo / "workshop-deploy-agent").mkdir()
        deploy_config = self.repo / "workshop-deploy-agent/config.yaml"
        deploy_config.write_text(
            'name: Workshop Deploy Agent\nversion: "2.3.4"\n',
            encoding="utf-8",
        )

        config_path = self.agent.config_path_for_target(
            self.repo,
            "deploy_agent.py",
        )

        self.assertEqual(config_path, deploy_config.resolve())

    def test_preflight_refuses_dirty_repository_before_fetch(self):
        calls = []

        def fake_require_command(command, root, failure):
            calls.append(command)

            if command == ["git", "status", "--porcelain"]:
                return " M deploy_agent.py"

            return ""

        original_require_command = self.agent.require_command
        self.agent.require_command = fake_require_command

        try:
            with self.assertRaisesRegex(
                self.agent.DeployError,
                "uncommitted changes",
            ):
                self.agent.preflight_git_sync(self.repo)
        finally:
            self.agent.require_command = original_require_command

        self.assertEqual(calls, [["git", "status", "--porcelain"]])

    def test_preflight_fast_forwards_when_behind_origin_main(self):
        responses = {
            ("git", "status", "--porcelain"): "",
            ("git", "branch", "--show-current"): "main",
            ("git", "fetch", "origin"): "",
            ("git", "rev-parse", "HEAD"): "local",
            ("git", "rev-parse", "origin/main"): "remote",
            ("git", "pull", "--ff-only"): "",
        }
        run_commands = []

        def fake_require_command(command, root, failure):
            return responses[tuple(command)]

        def fake_run_command(command, root):
            run_commands.append(command)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        original_require_command = self.agent.require_command
        original_run_command = self.agent.run_command
        self.agent.require_command = fake_require_command
        self.agent.run_command = fake_run_command

        try:
            result = self.agent.preflight_git_sync(self.repo)
        finally:
            self.agent.require_command = original_require_command
            self.agent.run_command = original_run_command

        self.assertEqual(result["status"], "fast_forwarded")
        self.assertIn(
            ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
            run_commands,
        )

    def test_preflight_refuses_local_ahead_repository(self):
        responses = {
            ("git", "status", "--porcelain"): "",
            ("git", "branch", "--show-current"): "main",
            ("git", "fetch", "origin"): "",
            ("git", "rev-parse", "HEAD"): "local",
            ("git", "rev-parse", "origin/main"): "remote",
        }

        def fake_require_command(command, root, failure):
            return responses[tuple(command)]

        def fake_run_command(command, root):
            class Result:
                stdout = ""
                stderr = ""

                if command == [
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    "HEAD",
                    "origin/main",
                ]:
                    returncode = 1
                else:
                    returncode = 0

            return Result()

        original_require_command = self.agent.require_command
        original_run_command = self.agent.run_command
        self.agent.require_command = fake_require_command
        self.agent.run_command = fake_run_command

        try:
            with self.assertRaisesRegex(
                self.agent.DeployError,
                "local commits",
            ):
                self.agent.preflight_git_sync(self.repo)
        finally:
            self.agent.require_command = original_require_command
            self.agent.run_command = original_run_command

    def test_preflight_refuses_diverged_repository(self):
        responses = {
            ("git", "status", "--porcelain"): "",
            ("git", "branch", "--show-current"): "main",
            ("git", "fetch", "origin"): "",
            ("git", "rev-parse", "HEAD"): "local",
            ("git", "rev-parse", "origin/main"): "remote",
        }

        def fake_require_command(command, root, failure):
            return responses[tuple(command)]

        def fake_run_command(command, root):
            class Result:
                returncode = 1
                stdout = ""
                stderr = ""

            return Result()

        original_require_command = self.agent.require_command
        original_run_command = self.agent.run_command
        self.agent.require_command = fake_require_command
        self.agent.run_command = fake_run_command

        try:
            with self.assertRaisesRegex(
                self.agent.DeployError,
                "diverged",
            ):
                self.agent.preflight_git_sync(self.repo)
        finally:
            self.agent.require_command = original_require_command
            self.agent.run_command = original_run_command


if __name__ == "__main__":
    unittest.main()
