from __future__ import annotations

import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_ai_assets as sync  # noqa: E402


class SyncPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = sync.collect_plan()

    def test_plan_is_idempotent(self) -> None:
        again = sync.collect_plan()
        self.assertEqual(set(self.plan.files), set(again.files))
        for key in self.plan.files:
            self.assertEqual(self.plan.files[key], again.files[key], key)

    def test_codex_agents_are_valid_toml(self) -> None:
        files = [
            key
            for key in self.plan.files
            if key.startswith(".codex/agents/") and key.endswith(".toml")
        ]
        self.assertTrue(files)
        for key in files:
            data, _ = self.plan.files[key]
            parsed = tomllib.loads(data.decode("utf-8"))
            for field in ("name", "description", "developer_instructions"):
                self.assertIn(field, parsed, key)
            self.assertEqual(parsed["name"], Path(key).stem, key)
            self.assertTrue(parsed["developer_instructions"].strip(), key)

    def test_agents_are_mirrored_in_all_targets(self) -> None:
        names = {agent.name for agent in sync.load_agents(sync.ROOT)}
        self.assertTrue(names)
        for name in names:
            self.assertIn(f".opencode/agents/{name}.md", self.plan.files)
            self.assertIn(f".claude/agents/{name}.md", self.plan.files)
            self.assertIn(f".codex/agents/{name}.toml", self.plan.files)

    def test_skills_and_flows_are_mirrored(self) -> None:
        skills = sync.validate_skills(sync.ROOT)
        flows = sync.load_flows(sync.ROOT)
        ids = {skill.name for skill in skills} | {flow.name for flow in flows}
        self.assertTrue(ids)
        for target in (".opencode", ".claude", ".agents"):
            for skill_id in ids:
                self.assertIn(f"{target}/skills/{skill_id}/SKILL.md", self.plan.files)

    def test_flows_disable_implicit_invocation(self) -> None:
        flows = sync.load_flows(sync.ROOT)
        for flow in flows:
            for target in (".opencode", ".claude", ".agents"):
                text = self.plan.files[f"{target}/skills/{flow.name}/SKILL.md"][0].decode("utf-8")
                self.assertIn("disable-model-invocation: true", text)
                self.assertIn(f"name: {flow.name}", text)
            self.assertIn(f".agents/skills/{flow.name}/agents/openai.yaml", self.plan.files)
            self.assertIn(f".opencode/commands/{flow.name}.md", self.plan.files)

    def test_flow_is_not_a_regular_skill(self) -> None:
        skills = {skill.name for skill in sync.validate_skills(sync.ROOT)}
        flows = {flow.name for flow in sync.load_flows(sync.ROOT)}
        self.assertFalse(skills & flows)

    def test_opencode_permissions_deny_disallowed_tools(self) -> None:
        permissions = sync.opencode_permissions(("read", "grep", "skill"))
        self.assertIn(("read", "allow"), permissions)
        self.assertIn(("grep", "allow"), permissions)
        self.assertIn(("skill", "allow"), permissions)
        self.assertIn(("edit", "deny"), permissions)
        self.assertIn(("shell", "deny"), permissions)
        self.assertIn(("subagent", "deny"), permissions)

    def test_toml_escape_roundtrip(self) -> None:
        text = 'linha 1\n"aspas" e \\ barra\n'
        escaped = sync.toml_escape_multiline(text)
        parsed = tomllib.loads(f'x = """\n{escaped}\n"""')
        self.assertEqual(parsed["x"].rstrip("\n"), text.strip())


class SyncWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = sync.collect_plan()

    def test_write_and_check_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync.write_plan(self.plan, root)
            self.assertEqual(sync.check_plan(self.plan, root), [])

    def test_check_detects_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync.write_plan(self.plan, root)
            path = root / ".opencode" / "agents" / "prompt-engineer.md"
            path.write_text(path.read_text(encoding="utf-8") + "\nmanual\n", encoding="utf-8")
            issues = sync.check_plan(self.plan, root)
            self.assertTrue(any("desatualizado" in issue for issue in issues), issues)

    def test_check_detects_stale_file_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync.write_plan(self.plan, root)
            stale = root / ".opencode" / "agents" / "stale.md"
            stale.write_text("stale", encoding="utf-8")
            manifest_path = root / ".opencode" / sync.MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"].append("agents/stale.md")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            issues = sync.check_plan(self.plan, root)
            self.assertTrue(any("obsoleto" in issue for issue in issues), issues)

    def test_write_removes_stale_file_on_next_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync.write_plan(self.plan, root)
            stale = root / ".opencode" / "agents" / "stale.md"
            stale.write_text("stale", encoding="utf-8")
            manifest_path = root / ".opencode" / sync.MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"].append("agents/stale.md")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            sync.write_plan(self.plan, root)
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
