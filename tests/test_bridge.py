import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "server" / "mcp_server.py"
SPEC = importlib.util.spec_from_file_location("ai_coop_server", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BridgeTests(unittest.TestCase):
    def test_default_runs_directory_is_outside_plugin_cache(self):
        # Windows 上放在用户主目录而非 LOCALAPPDATA：MSIX 宿主会重定向 AppData 下的新文件。
        with patch.object(MODULE.Path, "home", return_value=Path(r"C:\Users\tester")), \
                patch.object(MODULE.os, "name", "nt"):
            path = MODULE.default_runs_dir()
        self.assertEqual(path, Path(r"C:\Users\tester") / ".ai-coop" / "runs")

    def make_bridge(self, root: Path, allow_write: bool = False, host_agent: str = "codex"):
        return MODULE.Bridge(
            root=root,
            runs_dir=root / "data" / "runs",
            allow_write=allow_write,
            codex_exe=str(root / "missing-codex.exe"),
            claude_exe=str(root / "missing-claude.exe"),
            timeout_seconds=5,
            host_agent=host_agent,
        )

    def test_missing_cli_does_not_prevent_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp))
            with patch.object(MODULE.shutil, "which", return_value=None):
                health = bridge.health_check({})
            self.assertFalse(health["ok"])
            self.assertEqual(health["host_agent"], "codex")
            self.assertEqual(health["partner_agent"], "claude")

    def test_dynamic_mode_uses_each_explicit_current_workspace(self):
        with tempfile.TemporaryDirectory() as state_tmp, tempfile.TemporaryDirectory() as workspace_tmp:
            bridge = MODULE.Bridge(
                root=None,
                runs_dir=Path(state_tmp) / "runs",
                allow_write=False,
                codex_exe=None,
                claude_exe=None,
                timeout_seconds=5,
                host_agent="codex",
            )
            selected = bridge.resolve_workspace(str(Path(workspace_tmp).resolve()))
            self.assertEqual(selected, Path(workspace_tmp).resolve())
            with self.assertRaisesRegex(ValueError, "当前聊天"):
                bridge.resolve_workspace(None)

    def test_codex_app_cli_is_discovered_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "OpenAI" / "Codex" / "bin" / "build" / "codex.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"")
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False), patch.object(
                MODULE.shutil, "which", return_value=None
            ):
                found = MODULE.Bridge._resolve_executable(None, "codex")
            self.assertEqual(found, str(executable.resolve()))

    def test_legacy_root_argument_cannot_pin_the_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--root",
                    tmp,
                    "--runs-dir",
                    str(Path(tmp) / "runs"),
                    "--host-agent",
                    "codex",
                    "--self-test",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
                check=True,
            )
            payload = json.loads(completed.stdout)
            self.assertIsNone(payload["root"])
            self.assertEqual(payload["workspace_mode"], "current-chat")

    def test_tools_match_native_chat_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp))
            tools = {tool["name"]: tool for tool in bridge.tools()}
            self.assertIn("start_workflow", tools)
            self.assertIn("set_collaboration_mode", tools)
            self.assertIn("set_partner_preferences", tools)
            self.assertIn("show_partner_selector", tools)
            self.assertEqual(
                tools["show_partner_selector"]["_meta"]["ui"]["resourceUri"],
                MODULE.PARTNER_SELECTOR_URI,
            )
            self.assertIn("partner-selector-v2", MODULE.PARTNER_SELECTOR_URI)
            props = tools["start_workflow"]["inputSchema"]["properties"]
            self.assertIn("primary_agent", props)
            self.assertIn("partner_model", props)
            self.assertNotIn("controller", props)
            self.assertNotIn("executor", props)

    def test_host_always_selects_other_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_host = self.make_bridge(Path(tmp), host_agent="codex")
            claude_host = self.make_bridge(Path(tmp), host_agent="claude")
            self.assertEqual(codex_host.partner_for(codex_host.resolve_host_agent()), "claude")
            self.assertEqual(claude_host.partner_for(claude_host.resolve_host_agent()), "codex")

    def test_manual_partner_settings_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), host_agent="claude")
            with patch.object(bridge, "_start_job", return_value={"run_id": "test", "state": "queued"}):
                started = bridge.start_workflow({
                    "task": "分析选择",
                    "partner_selection": "manual",
                    "partner_model": "gpt-custom",
                    "partner_effort": "high",
                })
            self.assertEqual(started["route"]["primary_agent"], "claude")
            self.assertEqual(started["route"]["partner_agent"], "codex")
            self.assertEqual(started["route"]["partner_model"], "gpt-custom")

    def test_preferences_feed_future_chat_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), host_agent="codex")
            saved = bridge.set_partner_preferences({
                "partner_selection": "manual",
                "partner_model": "sonnet-custom",
                "partner_effort": "high",
            })
            self.assertTrue(saved["saved"])
            with patch.object(bridge, "_start_job", return_value={"run_id": "test", "state": "queued"}):
                started = bridge.start_workflow({"task": "复核我的方案"})
            self.assertEqual(started["route"]["partner_model"], "sonnet-custom")
            self.assertEqual(started["route"]["partner_effort"], "high")

    def test_opening_collaboration_persists_enabled_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), host_agent="codex")
            result = bridge.set_collaboration_mode({"enabled": True})
            self.assertTrue(result["enabled"])
            self.assertTrue(bridge._read_preferences()["enabled"])
            catalog = bridge.get_model_catalog({})
            self.assertTrue(catalog["collaboration_enabled"])

    def test_auto_collab_hook_only_injects_when_enabled_and_not_nested(self):
        hook_path = MODULE_PATH.parents[1] / "scripts" / "auto-collab-hook.py"
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / ".ai-coop"
            state_dir.mkdir(parents=True)
            event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "检查方案"})
            env = os.environ.copy()
            env["USERPROFILE"] = tmp

            inactive = subprocess.run(
                [sys.executable, str(hook_path)], input=event, capture_output=True,
                text=True, encoding="utf-8", env=env, check=True,
            )
            self.assertEqual(inactive.stdout, "")

            (state_dir / "preferences.json").write_text(
                json.dumps({"enabled": True}), encoding="utf-8"
            )
            active = subprocess.run(
                [sys.executable, str(hook_path)], input=event, capture_output=True,
                text=True, encoding="utf-8", env=env, check=True,
            )
            payload = json.loads(active.stdout)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn("start_workflow", context)
            self.assertIn("不要让用户输入 workflow", context)
            self.assertIn("任务包", context)
            self.assertTrue(active.stdout.isascii())  # 宿主按 UTF-8 读取，输出须与代码页无关

            env["AI_COOP_NESTED"] = "1"
            nested = subprocess.run(
                [sys.executable, str(hook_path)], input=event, capture_output=True,
                text=True, encoding="utf-8", env=env, check=True,
            )
            self.assertEqual(nested.stdout, "")

    def test_host_env_vars_are_not_leaked_to_partner_claude(self):
        self.assertTrue(MODULE._host_env_var("ANTHROPIC_BASE_URL"))
        self.assertTrue(MODULE._host_env_var("ANTHROPIC_AUTH_TOKEN"))
        self.assertTrue(MODULE._host_env_var("CLAUDE_CODE_SESSION_ID"))
        self.assertTrue(MODULE._host_env_var("CLAUDECODE"))
        self.assertFalse(MODULE._host_env_var("CLAUDE_CODE_GIT_BASH_PATH"))
        self.assertFalse(MODULE._host_env_var("PATH"))

    def _claude_stream(self, *events):
        return "\n".join(json.dumps(e) for e in events)

    def test_partner_claude_official_account_skips_user_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), host_agent="codex")
            stdout = self._claude_stream(
                {"type": "system", "subtype": "init", "model": "claude-sonnet-5"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "结论"}]}},
                {"type": "result", "is_error": False, "result": "结论", "usage": {"output_tokens": 3}},
            )
            with patch.object(bridge, "executable", return_value="claude"),                     patch.object(bridge, "_run_process", return_value=(stdout, "")) as run:
                result, meta = bridge.run_claude("问题", Path(tmp))
            argv = run.call_args.args[0]
            self.assertIn("--setting-sources", argv)
            self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")
            self.assertIn("stream-json", argv)
            self.assertIs(run.call_args.kwargs["drop_env"], MODULE._host_env_var)
            self.assertEqual(result, "结论")
            self.assertEqual(meta["actual_model"], "claude-sonnet-5")

    def test_partner_claude_in_home_dir_skips_project_settings_too(self):
        self.assertEqual(MODULE.claude_official_args(Path.home()), ["--setting-sources", "local"])
        self.assertEqual(MODULE.claude_official_args(Path(__file__).parent),
                         ["--setting-sources", "project,local"])

    def test_panel_only_lists_runs_in_its_own_direction(self):
        spec = importlib.util.spec_from_file_location("ai_coop_sidebar", MODULE_PATH.with_name("sidebar.py"))
        sidebar = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(MODULE_PATH.parent))
        spec.loader.exec_module(sidebar)
        self.assertEqual(sidebar.run_partner({"route": {"partner_agent": "codex"}}), "codex")
        self.assertEqual(sidebar.run_partner({"agent_settings": {"claude": {"model": "sonnet"}}}), "claude")
        self.assertEqual(sidebar.run_partner({"agent_settings": {"agent": "claude", "model": "opus"}}), "claude")
        self.assertEqual(sidebar.run_partner({"agent_settings": {"model": "gpt-x", "effort": "high"}}), "codex")
        self.assertEqual(sidebar.run_partner({"agent_settings": {"codex": {}, "claude": {}}}), "both")

    def test_claude_partner_cannot_be_asked_to_implement(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), allow_write=True, host_agent="codex")
            with self.assertRaisesRegex(ValueError, "只做分析与审查"):
                bridge.start_workflow({"task": "改代码", "mode": "implement", "approved_decision": "已批准"})

    def test_partner_claude_not_logged_in_explains_how_to_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), host_agent="codex")
            stdout = self._claude_stream(
                {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"})
            with patch.object(bridge, "executable", return_value="claude"),                     patch.object(bridge, "_run_process", return_value=(stdout, "")):
                with self.assertRaises(RuntimeError) as ctx:
                    bridge.run_claude("问题", Path(tmp))
            self.assertIn("claude auth login", str(ctx.exception))

    def test_claude_efforts_are_detected_from_installed_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), host_agent="codex")
            completed = subprocess.CompletedProcess(
                ["claude", "--help"],
                0,
                stdout="--effort <level>  Effort (low, medium, high, xhigh, max)\n",
                stderr="",
            )
            with patch.object(bridge, "executable", return_value="claude"), patch.object(
                MODULE.subprocess, "run", return_value=completed
            ):
                catalog = bridge.get_model_catalog({})
            self.assertEqual(catalog["partner_agent"], "claude")
            self.assertEqual(
                catalog["partner_efforts"], ["low", "medium", "high", "xhigh", "max"]
            )
            self.assertTrue(catalog["partner"]["efforts_verified"])

    def test_exact_claude_model_is_recovered_from_run_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), host_agent="codex")
            run_dir = bridge.runs_dir / "finished-run"
            run_dir.mkdir(parents=True)
            (run_dir / "usage.json").write_text(
                json.dumps({
                    "calls": [{
                        "provider": "claude",
                        "model": "sonnet",
                        "model_usage": {"vendor-model-x": {"inputTokens": 1}},
                    }]
                }),
                encoding="utf-8",
            )
            # 账号模型接口不可用时（未登录/离线）才退回运行历史+别名；测试里不访问真实网络。
            with patch.object(bridge, "executable", return_value=None), \
                    patch.object(MODULE, "_claude_account_models", return_value=[]):
                catalog = bridge.get_model_catalog({})
            models = catalog["partner"]["models"]
            exact = next(item for item in models if item["id"] == "vendor-model-x")
            alias = next(item for item in models if item["id"] == "sonnet")
            self.assertTrue(exact["verified"])
            self.assertFalse(alias["verified"])
            self.assertTrue(catalog["partner"]["verified"])

    def test_implementation_requires_human_approval_and_write_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make_bridge(Path(tmp), allow_write=False, host_agent="claude")
            with self.assertRaises(PermissionError):
                bridge.start_workflow({"task": "修改文件", "mode": "implement", "approved_decision": "已批准"})

    def test_stdio_protocol_exposes_tools_and_compact_ui_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "resources/read",
                    "params": {"uri": MODULE.PARTNER_SELECTOR_URI},
                },
                {"jsonrpc": "2.0", "id": 5, "method": "prompts/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "prompts/get",
                    "params": {"name": "open_ai_coop"},
                },
            ]
            completed = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--root", tmp, "--runs-dir", str(Path(tmp) / "runs"), "--host-agent", "codex"],
                input="\n".join(json.dumps(item) for item in messages) + "\n\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
                check=True,
            )
            responses = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(len(responses), 6)
            self.assertIn("resources", responses[0]["result"]["capabilities"])
            self.assertIn("prompts", responses[0]["result"]["capabilities"])
            self.assertIn("Never ask the user", responses[0]["result"]["instructions"])
            self.assertTrue(any(t["name"] == "set_collaboration_mode" for t in responses[1]["result"]["tools"]))
            self.assertTrue(any(t["name"] == "set_partner_preferences" for t in responses[1]["result"]["tools"]))
            self.assertTrue(any(t["name"] == "show_partner_selector" for t in responses[1]["result"]["tools"]))
            self.assertEqual(responses[2]["result"]["resources"][0]["uri"], MODULE.PARTNER_SELECTOR_URI)
            content = responses[3]["result"]["contents"][0]
            self.assertEqual(content["mimeType"], "text/html;profile=mcp-app")
            self.assertIn("set_partner_preferences", content["text"])
            self.assertIn('id="toggle"', content["text"])
            self.assertIn('list="models"', content["text"])
            self.assertNotIn("127.0.0.1", content["text"])
            self.assertEqual(responses[4]["result"]["prompts"][0]["name"], "open_ai_coop")
            self.assertIn("show_partner_selector", responses[5]["result"]["messages"][0]["content"]["text"])


if __name__ == "__main__":
    unittest.main()
