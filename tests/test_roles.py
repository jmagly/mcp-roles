"""Public role wrappers with real rendering and stub provider executables."""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "roles"
PROVIDERS = ("claude", "codex", "hermes", "muse")
FLAGS = {
    "claude": "--dangerously-skip-permissions",
    "codex": "--dangerously-bypass-approvals-and-sandbox",
    "hermes": "--yolo",
    "muse": "--yolo",
}


@unittest.skipUnless(shutil.which("jq"), "requires jq")
class RoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.catalog = self.base / "roles"
        shutil.copytree(EXAMPLES, self.catalog, ignore=shutil.ignore_patterns("README.md"))
        self.capture = self.base / "capture.json"
        self.copy = self.base / "rendered.json"
        self.stub = self.base / "provider-stub"
        self.stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, shutil, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['ROLE_TEST_CAPTURE']).write_text(json.dumps({"
            "'args': sys.argv[1:], 'home': os.environ.get('HOME'), "
            "'hermes_home': os.environ.get('HERMES_HOME'), 'codex_home': os.environ.get('CODEX_HOME'), "
            "'xdg': os.environ.get('XDG_CONFIG_HOME')}))\n"
            "if '--mcp-config' in sys.argv:\n"
            "    source = sys.argv[sys.argv.index('--mcp-config') + 1]\n"
            "    assert Path(source).stat().st_mode & 0o777 == 0o600\n"
            "    assert Path(source).parent.stat().st_mode & 0o777 == 0o700\n"
            "    shutil.copyfile(source, os.environ['ROLE_TEST_COPY'])\n"
            "sys.exit(int(os.environ.get('ROLE_TEST_STATUS', '0')))\n"
        )
        self.stub.chmod(0o755)
        (self.base / ".codex").mkdir()
        (self.base / ".codex" / "config.toml").write_text(
            'model = "test"\n[mcp_servers.old]\nurl = "old"\n'
            '[profiles.test]\nmodel = "other"\n'
        )
        (self.base / ".hermes").mkdir()
        (self.base / ".hermes" / "config.yaml").write_text("model: test\n")
        muse = self.base / ".config" / "muse"
        muse.mkdir(parents=True)
        (muse / "settings.json").write_text('{"schema_version": 1, "marker": "kept"}\n')
        (muse / "auth.json").write_text("{}\n")
        self.env = dict(os.environ)
        self.env.update({
            "MCP_ROLES_BASE_HOME": str(self.base),
            "MCP_ROLES_DIR": str(self.catalog),
            "ROLE_TEST_CAPTURE": str(self.capture),
            "ROLE_TEST_COPY": str(self.copy),
            "GITHUB_PAT": "example-value",
        })
        for provider in PROVIDERS:
            self.env[f"MCP_ROLES_{provider.upper()}_BIN"] = str(self.stub)

    def invoke(self, provider, *args, env=None, status=0, shell=None):
        self.capture.unlink(missing_ok=True)
        self.copy.unlink(missing_ok=True)
        effective = dict(self.env if env is None else env)
        effective["ROLE_TEST_STATUS"] = str(status)
        script = 'source "$1"; source "$2"; shift 2; "$provider-role" "$@"'
        effective["provider"] = provider
        result = subprocess.run(
            [shell or os.environ.get("MCP_ROLES_TEST_SHELL", "bash"), "-c", script, "test", str(ROOT / "lib/core.sh"),
             str(ROOT / "providers" / f"{provider}.sh"), *args],
            cwd=ROOT, env=effective, text=True, capture_output=True,
        )
        captured = json.loads(self.capture.read_text()) if self.capture.exists() else None
        return result, captured

    def test_zsh_launch_status_and_empty_catalog(self):
        if not shutil.which("zsh"):
            self.skipTest("requires zsh")
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                result, captured = self.invoke(provider, "minimal", "prompt with spaces",
                                               status=23, shell="zsh")
                self.assertEqual(result.returncode, 23, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertIn("prompt with spaces", captured["args"])
                env = dict(self.env, MCP_ROLES_DIR=str(self.base / "empty"))
                result, _ = self.invoke(provider, shell="zsh", env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")

    def test_no_shell_state_leaks(self):
        for shell in ("bash", "zsh"):
            if not shutil.which(shell):
                continue
            for provider in PROVIDERS:
                script = '''
before_options=$(set +o)
before_umask=$(umask)
source "$1"
source "$2"
MCP_ROLES_ROLE=sentinel
MCP_ROLES_CONSUMED=42
MCP_ROLES_BYPASS_MODE=sentinel
"$3-role" minimal >/dev/null || exit 1
[[ "$MCP_ROLES_ROLE:$MCP_ROLES_CONSUMED:$MCP_ROLES_BYPASS_MODE" == sentinel:42:sentinel ]] || exit 2
[[ "$(set +o)" == "$before_options" && "$(umask)" == "$before_umask" ]] || exit 3
'''
                result = subprocess.run([shell, "-c", script, "test", str(ROOT / "lib/core.sh"),
                                         str(ROOT / "providers" / f"{provider}.sh"), provider],
                                        env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, (shell, provider, result.stderr))

    def test_plain_role_launch_under_bash_nounset(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                script = 'set -u; source "$1"; source "$2"; "$3-role" minimal'
                result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "lib/core.sh"),
                                         str(ROOT / "providers" / f"{provider}.sh"), provider],
                                        env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_claude_end_of_options_keeps_config_an_option(self):
        result, captured = self.invoke("claude", "minimal", "--", "--safe", "--yolo", "two words")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = captured["args"]
        self.assertLess(argv.index("--mcp-config"), argv.index("--"))
        self.assertEqual(argv[argv.index("--") + 1:], ["--safe", "--yolo", "two words"])
        self.assertEqual(argv[argv.index("--") - 2], "--mcp-config")

    def test_muse_yolo_option_values_are_data(self):
        for args in (("-p", "--yolo"), ("exec", "--model", "--yolo"),
                     ("exec", "--", "--yolo")):
            result, captured = self.invoke("muse", "minimal", "--safe", *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(captured["args"], list(args))

    def test_codex_removes_all_base_mcp_tables(self):
        config = self.base / ".codex/config.toml"
        config.write_text('''model = "test"
developer_instructions = """Keep this text:
[mcp_servers.not_a_table]
literal text
"""
  [ "mcp_servers" . old ]
url = "old"
  [ "mcp_servers" . old . env ]
TOKEN = "old-secret"
  [profiles.test]
model = "other"
''')
        result, _ = self.invoke("codex", "docs")
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = self.base / ".codex/roles-runtime/docs/.codex/config.toml"
        parsed = tomllib.loads(runtime.read_text())
        original = tomllib.loads(config.read_text())
        self.assertEqual(set(parsed["mcp_servers"]), {"context7"})
        del parsed["mcp_servers"], original["mcp_servers"]
        self.assertEqual(parsed, original)

    def test_codex_toml_forms_and_values_round_trip(self):
        base = '''"model" = "test"
enabled = true
count = 42
ratio = 1.25
timestamp = 1979-05-27T07:32:00Z
date = 1979-05-27
time = 07:32:00
items = ["spaces and \\"quotes\\"", {nested = [1, 2]}]
'''
        forms = (
            '[mcp_servers.old]\nurl="old"\n[mcp_servers.old.env]\nKEY="secret"\n',
            "['mcp_servers'.old]\nurl='old'\n['mcp_servers'.old.env]\nKEY='secret'\n",
            'mcp_servers.old.url = "old"\nmcp_servers.old.env.KEY = "secret"\n',
            'mcp_servers = {old = {url = "old", env = {KEY = "secret"}}}\n',
        )
        for form in forms:
            with self.subTest(form=form):
                (self.base / ".codex/config.toml").write_text(base + form)
                result, _ = self.invoke("codex", "minimal")
                self.assertEqual(result.returncode, 0, result.stderr)
                runtime = self.base / ".codex/roles-runtime/minimal/.codex/config.toml"
                self.assertEqual(tomllib.loads(runtime.read_text()), tomllib.loads(base))

    def test_codex_home_override_cannot_escape_runtime(self):
        env = dict(self.env, CODEX_HOME=str(self.base / ".codex"))
        result, captured = self.invoke("codex", "minimal", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured["codex_home"],
                         str(self.base / ".codex/roles-runtime/minimal/.codex"))

    def test_codex_invalid_base_config_does_not_launch(self):
        (self.base / ".codex/config.toml").write_text('[invalid')
        result, captured = self.invoke("codex", "minimal")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(captured)

    def test_runtime_directories_and_secret_files_are_private(self):
        runtimes = {
            "codex": self.base / ".codex/roles-runtime/github",
            "hermes": self.base / ".hermes/roles-runtime/github",
            "muse": self.base / ".config/muse/roles-runtime/github",
        }
        for provider, runtime in runtimes.items():
            with self.subTest(provider=provider):
                runtime.mkdir(parents=True, exist_ok=True)
                runtime.chmod(0o755)
                result, _ = self.invoke(provider, "github")
                self.assertEqual(result.returncode, 0, result.stderr)
                for directory in [runtime.parent, runtime, *runtime.rglob("*")]:
                    if directory.is_dir() and not directory.is_symlink():
                        self.assertEqual(directory.stat().st_mode & 0o777, 0o700, str(directory))
                for config in runtime.rglob("*"):
                    if config.is_file() and not config.is_symlink():
                        self.assertEqual(config.stat().st_mode & 0o777, 0o600, str(config))

    def test_env_and_role_values_are_never_executed_or_reexpanded(self):
        marker = self.base / "injected"
        payload = f'$(touch {marker}); `touch {marker}` \\" ${{UNSET_NESTED}}'
        role = {"mcpServers": {"literal": {"command": payload, "args": ["${PAYLOAD}"],
                                         "env": {"VALUE": "${PAYLOAD}"}},
                               "remote": {"url": "${PAYLOAD}", "headers": {"X": "${PAYLOAD}"}}}}
        (self.catalog / "literal.json").write_text(json.dumps(role))
        env = dict(self.env, PAYLOAD=payload)
        env.pop("UNSET_NESTED", None)
        # A literal role placeholder must still fail if unset.
        result, captured = self.invoke("claude", "literal", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(captured)
        role["mcpServers"]["literal"]["command"] = "${PAYLOAD}"
        (self.catalog / "literal.json").write_text(json.dumps(role))
        for provider in PROVIDERS:
            result, captured = self.invoke(provider, "literal", env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            if provider == "claude":
                rendered = json.loads(self.copy.read_text())["mcpServers"]
                self.assertEqual(rendered["literal"]["command"], payload)
                self.assertEqual(rendered["literal"]["args"], [payload])

    def test_safe_default_yolo_and_environment_override(self):
        for provider in PROVIDERS:
            cases = [
                (("minimal",), None, False),
                (("--yolo", "minimal"), None, True),
                (("minimal", "--yolo"), None, True),
                (("--safe", "minimal"), "1", False),
                (("minimal", "--safe"), "1", False),
                (("minimal",), "1", True),
            ]
            for args, env_bypass, bypass in cases:
                with self.subTest(provider=provider, args=args, env_bypass=env_bypass):
                    env = dict(self.env)
                    if env_bypass:
                        env["MCP_ROLES_BYPASS"] = env_bypass
                    else:
                        env.pop("MCP_ROLES_BYPASS", None)
                    result, captured = self.invoke(provider, *args, env=env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    argv = captured["args"]
                    if provider == "claude":
                        self.assertIn("--strict-mcp-config", argv)
                    self.assertEqual(FLAGS[provider] in argv, bypass)

    def test_provider_args_and_exit_status(self):
        for provider in PROVIDERS:
            args = ("minimal", "-p", "prompt with 'quotes' and $literal")
            result, captured = self.invoke(provider, *args, status=23)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertIn(args[-1], captured["args"])
            result, captured = self.invoke(provider, "minimal", "-p", "--safe")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--safe", captured["args"])
            result, captured = self.invoke(provider, "minimal", "--", "--safe", "--yolo",
                                           "spaces; 'quotes' $literal", "")
            self.assertEqual(result.returncode, 0, result.stderr)
            argv = captured["args"]
            self.assertEqual(argv[argv.index("--") + 1:],
                             ["--safe", "--yolo", "spaces; 'quotes' $literal", ""])

    def test_claude_flag_order_and_oauth_strip(self):
        result, captured = self.invoke("claude", "notion", "--resume")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = captured["args"]
        self.assertEqual(argv[:2], ["--strict-mcp-config", "--resume"])
        self.assertEqual(argv[-2], "--mcp-config")
        self.assertEqual(json.loads(self.copy.read_text())["mcpServers"]["notion"],
                         {"type": "http", "url": "https://mcp.notion.com/mcp"})

    def test_codex_config_render_and_sqlite_isolation(self):
        for name in ("auth.json", "cache", "history.jsonl", "installation_id",
                     "memories", "models_cache.json", "prompts", "rules", "skills",
                     "version.json"):
            (self.base / ".codex" / name).touch()
        source = sqlite3.connect(self.base / ".codex" / "state_5.sqlite")
        self.addCleanup(source.close)
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE identity (name TEXT)")
        source.execute("INSERT INTO identity VALUES ('base')")
        source.commit()
        result, captured = self.invoke("codex", "full")
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = self.base / ".codex" / "roles-runtime" / "full" / ".codex"
        config = (runtime / "config.toml").read_text()
        self.assertEqual(captured["home"], str(runtime.parent))
        parsed = tomllib.loads(config)
        self.assertEqual(parsed["model"], "test")
        self.assertEqual(parsed["profiles"]["test"]["model"], "other")
        self.assertNotIn("mcp_servers.old", config)
        self.assertIn('[mcp_servers."github"]', config)
        self.assertIn('http_headers = {"Authorization" = "Bearer example-value"}', config)
        self.assertIn('[mcp_servers."playwright"]', config)
        self.assertIn('command = "npx"', config)
        self.assertIn('args = ["-y", "@playwright/mcp@latest"]', config)
        self.assertIn('url = "https://mcp.notion.com/mcp"', config)
        for name in ("auth.json", "cache", "history.jsonl", "installation_id",
                     "memories", "models_cache.json", "prompts", "rules", "skills",
                     "version.json"):
            self.assertTrue((runtime / name).is_symlink(), name)
        self.assertFalse((runtime / "state_5.sqlite").is_symlink())
        for suffix in ("-wal", "-shm"):
            self.assertFalse((runtime / ("state_5.sqlite" + suffix)).is_symlink())
        self.assertEqual(source.execute("SELECT name FROM identity").fetchall(), [("base",)])

        # An existing role database must remain independent on another launch.
        with sqlite3.connect(runtime / "state_5.sqlite") as connection:
            connection.execute("CREATE TABLE identity (name TEXT)")
            connection.execute("INSERT INTO identity VALUES ('role')")
        result, _ = self.invoke("codex", "full")
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(runtime / "state_5.sqlite") as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT name FROM identity").fetchall(), [("role",)])
        self.assertEqual(source.execute("SELECT name FROM identity").fetchall(), [("base",)])

    def test_codex_custom_env_and_headers(self):
        (self.catalog / "custom.json").write_text(json.dumps({"mcpServers": {
            "stdio": {"command": "${MCP_TEST_COMMAND}", "args": ["${MCP_TEST_ARG}"],
                      "env": {"KEY": "${MCP_TEST_VALUE}"}},
            "remote": {"url": "https://example.com/${MCP_TEST_PATH}",
                       "headers": {"X-Test": "${MCP_TEST_VALUE}"}},
        }}))
        env = dict(self.env, MCP_TEST_COMMAND="tool", MCP_TEST_ARG="with spaces",
                   MCP_TEST_VALUE="a\"b", MCP_TEST_PATH="mcp")
        result, _ = self.invoke("codex", "custom", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = (self.base / ".codex" / "roles-runtime" / "custom" / ".codex" / "config.toml").read_text()
        self.assertIn('command = "tool"', config)
        self.assertIn('args = ["with spaces"]', config)
        self.assertIn('env = {"KEY" = "a\\\"b"}', config)
        self.assertIn('http_headers = {"X-Test" = "a\\\"b"}', config)
        self.assertIn('url = "https://example.com/mcp"', config)

    def test_hermes_oauth_mapping_and_shared_state(self):
        if not shutil.which("yq"):
            self.skipTest("requires yq v4")
        (self.base / ".hermes" / "auth.json").write_text("{}")
        result, captured = self.invoke("hermes", "notion")
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = self.base / ".hermes" / "roles-runtime" / "notion"
        self.assertEqual(captured["hermes_home"], str(runtime))
        self.assertTrue((runtime / "auth.json").is_symlink())
        self.assertTrue((runtime / "mcp-tokens").is_symlink())
        rendered = (runtime / "config.yaml").read_text()
        self.assertIn("auth: oauth", rendered)
        self.assertNotIn("oauth: true", rendered)
        self.assertNotIn("type: http", rendered)

    def test_muse_merge_and_flag_placement(self):
        cases = [
            (("minimal", "exec", "--provider", "test"), ["exec", "--provider", "test", "--yolo"]),
            (("minimal", "exec", "--", "hello"), ["exec", "--yolo", "--", "hello"]),
            (("minimal", "mcp", "login", "notion"), None),
            (("minimal", "--", "--yolo"), ["--yolo", "--", "--yolo"]),
            (("minimal", "exec", "--yolo"), ["exec", "--yolo"]),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                if args[1:3] == ("mcp", "login"):
                    args = ("notion", *args[1:])
                    expected = ["mcp", "login", "notion"]
                result, captured = self.invoke("muse", "--yolo", *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(captured["args"], expected)
        result, captured = self.invoke("muse", "notion")
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = self.base / ".config" / "muse" / "roles-runtime" / "notion"
        settings = json.loads((runtime / "muse" / "settings.json").read_text())
        self.assertEqual(settings["marker"], "kept")
        self.assertNotIn("oauth", settings["mcpServers"]["notion"])
        self.assertTrue((runtime / "muse" / "auth.json").is_symlink())
        self.assertEqual(captured["xdg"], str(runtime))

    def test_login_validation_suggests_role(self):
        for provider in ("codex", "hermes", "muse"):
            result, captured = self.invoke(provider, "minimal", "mcp", "login", "notion")
            self.assertEqual(result.returncode, 1)
            self.assertIsNone(captured)
            self.assertIn("Available in role(s):", result.stderr)
            self.assertIn(f"Try: {provider}-role", result.stderr)
            result, captured = self.invoke(provider, "notion", "mcp", "login", "notion")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNotNone(captured)

    def test_unset_environment_variable_names_var(self):
        env = dict(self.env)
        env.pop("GITHUB_PAT")
        for provider in PROVIDERS:
            result, captured = self.invoke(provider, "github", env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(captured)
            self.assertIn("GITHUB_PAT", result.stderr)

    def test_help_unknown_role_and_cli_validate(self):
        for provider in PROVIDERS:
            result, captured = self.invoke(provider)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--yolo", result.stdout)
            self.assertIsNone(captured)
            result, captured = self.invoke(provider, "missing")
            self.assertEqual(result.returncode, 1)
            self.assertIsNone(captured)
        cli = ROOT / "bin" / "mcp-roles"
        result = subprocess.run([str(cli), "validate"], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.catalog / "broken.json").write_text('{"mcpServers": {"bad": {}}}')
        result = subprocess.run([str(cli), "validate"], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("broken.json", result.stderr)
        (self.catalog / "broken.json").write_text('{"mcpServers": []}')
        result = subprocess.run([str(cli), "validate"], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        (self.catalog / "broken.json").write_text('{')
        result = subprocess.run([str(cli), "validate"], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)

    def test_installer_idempotency_and_uninstall(self):
        env = dict(self.env, SHELL="/bin/bash")
        installer = ROOT / "install.sh"
        previous_rc = None
        for _ in range(2):
            result = subprocess.run([str(installer), "--providers", "claude,muse"],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            current_rc = (self.base / ".bashrc").read_text()
            if previous_rc is not None:
                self.assertEqual(current_rc, previous_rc)
            previous_rc = current_rc
        rc = (self.base / ".bashrc").read_text()
        self.assertEqual(rc.count("# >>> mcp-roles >>>"), 1)
        init = (self.base / ".local" / "share" / "mcp-roles" / "init.sh").read_text()
        self.assertIn("providers/claude.sh", init)
        self.assertIn("providers/muse.sh", init)
        self.assertNotIn("providers/codex.sh", init)
        self.assertTrue((self.base / ".local" / "bin" / "mcp-roles").is_symlink())
        result = subprocess.run([str(self.base / ".local/bin/mcp-roles"), "list"],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("minimal", result.stdout)
        (self.catalog / "custom.json").write_text('{"mcpServers": {}}')
        subprocess.run([str(installer), "--providers", "claude"], env=env, check=True,
                       capture_output=True, text=True)
        self.assertTrue((self.catalog / "custom.json").exists())
        result = subprocess.run([str(ROOT / "uninstall.sh")], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.catalog.exists())
        self.assertEqual((self.base / ".bashrc").read_text().count("# >>> mcp-roles >>>"), 0)
        self.assertIn("Left catalog:", result.stdout)

    def test_installer_unsupported_shell_skips_rc_and_empty_detection_warns(self):
        empty_bin = self.base / "empty-bin"
        empty_bin.mkdir()
        for name in ("bash", "dirname", "id", "getent", "cut", "mkdir", "cp", "pwd", "readlink", "ln"):
            executable = shutil.which(name)
            if executable:
                (empty_bin / name).symlink_to(executable)
        env = dict(self.env, SHELL="/bin/sh", PATH=str(empty_bin))
        for provider in PROVIDERS:
            env.pop(f"MCP_ROLES_{provider.upper()}_BIN")
        result = subprocess.run([str(ROOT / "install.sh")], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no provider CLIs", result.stderr)
        self.assertIn("unsupported SHELL", result.stderr)
        self.assertFalse((self.base / ".bashrc").exists())
        self.assertFalse((self.base / ".zshrc").exists())
        init = (self.base / ".local/share/mcp-roles/init.sh").read_text()
        self.assertNotIn("/providers/", init)

    def test_installer_rejects_bad_rc_target_before_installing(self):
        rc = self.base / ".bashrc"
        rc.mkdir()
        env = dict(self.env, SHELL="/bin/bash")
        result = subprocess.run([str(ROOT / "install.sh"), "--providers", "claude"],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("rc target is not a writable file", result.stderr)
        self.assertFalse((self.base / ".local/share/mcp-roles").exists())

    def test_doctor_optional_dependencies_follow_detected_providers(self):
        tools_dir = self.base / "doctor-bin"
        tools_dir.mkdir()
        for name in ("bash", "dirname", "jq", "tr"):
            (tools_dir / name).symlink_to(shutil.which(name))
        env = dict(self.env, PATH=str(tools_dir))
        env["MCP_ROLES_CODEX_BIN"] = str(self.base / "missing-codex")
        env["MCP_ROLES_HERMES_BIN"] = str(self.base / "missing-hermes")
        cli = ROOT / "bin/mcp-roles"
        result = subprocess.run([str(cli), "doctor"], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OPTIONAL dependency yq", result.stdout)
        self.assertIn("OPTIONAL dependency Python 3.11+", result.stdout)
        env["MCP_ROLES_CODEX_BIN"] = str(self.stub)
        env["MCP_ROLES_HERMES_BIN"] = str(self.stub)
        result = subprocess.run([str(cli), "doctor"], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("MISSING dependency yq", result.stdout)
        self.assertIn("MISSING dependency Python 3.11+", result.stdout)

    def test_system_bash_32_rejects_install_and_sourced_core(self):
        system_bash = Path("/bin/bash")
        if not system_bash.exists():
            self.skipTest("requires /bin/bash 3.2 (checked in macOS CI)")
        version = subprocess.run([str(system_bash), "-c", "printf '%s' \"${BASH_VERSINFO[0]}\""],
                                 capture_output=True, text=True)
        if version.stdout != "3":
            self.skipTest("requires /bin/bash 3.2 (checked in macOS CI)")
        for command in ((str(system_bash), str(ROOT / "install.sh")),
                        (str(system_bash), "-c", f'source "{ROOT / "lib/core.sh"}"')):
            result = subprocess.run(command, env=self.env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("bash 4+ or zsh required (macOS: brew install bash)", result.stderr)

    def test_uninstall_preserves_user_data_inside_prefix(self):
        prefix = self.base / "install with spaces"
        catalog = prefix / "roles"
        env = dict(self.env, SHELL="/bin/bash", MCP_ROLES_DIR=str(catalog))
        result = subprocess.run([str(ROOT / "install.sh"), "--prefix", str(prefix),
                                 "--providers", "claude"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        user_file = prefix / "lib/user-data.txt"
        user_file.write_text("user data")
        custom = catalog / "custom.json"
        custom.write_text('{"mcpServers": {}}')
        rc = self.base / ".bashrc"
        rc.write_text(rc.read_text() + 'export USER_SETTING=kept\n')
        result = subprocess.run([str(ROOT / "uninstall.sh"), "--prefix", str(prefix)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(user_file.read_text(), "user data")
        self.assertEqual(custom.read_text(), '{"mcpServers": {}}')
        self.assertEqual(rc.read_text(), 'export USER_SETTING=kept\n')
        self.assertFalse((prefix / "lib/core.sh").exists())

    def test_malformed_rc_markers_never_erase_user_content(self):
        env = dict(self.env, SHELL="/bin/bash")
        for script in ("install.sh", "uninstall.sh"):
            for markers in ("# >>> mcp-roles >>>\n", "# <<< mcp-roles <<<\n",
                            "# >>> mcp-roles >>>\n# >>> mcp-roles >>>\n# <<< mcp-roles <<<\n"):
                rc = self.base / ".bashrc"
                content = 'export BEFORE=yes\n' + markers + 'export IMPORTANT=yes\n'
                rc.write_text(content)
                args = [str(ROOT / script)]
                if script == "install.sh":
                    args += ["--providers", "claude"]
                result = subprocess.run(args, env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, (script, markers))
                self.assertEqual(rc.read_text(), content)

    def test_uninstall_other_prefix_keeps_active_rc_block(self):
        env = dict(self.env, SHELL="/bin/bash")
        subprocess.run([str(ROOT / "install.sh"), "--providers", "claude"],
                       env=env, capture_output=True, check=True)
        rc = self.base / ".bashrc"
        before = rc.read_text()
        result = subprocess.run([str(ROOT / "uninstall.sh"), "--prefix", str(self.base / "other")],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(rc.read_text(), before)

    def test_relative_install_prefix_and_quoted_init_in_both_shells(self):
        # Literal shell syntax in a filesystem path must never be evaluated.
        relative = "install $(touch injected) 'quoted'"
        for shell in ("bash", "zsh"):
            if not shutil.which(shell):
                continue
            env = dict(self.env, SHELL=f"/bin/{shell}")
            result = subprocess.run([str(ROOT / "install.sh"), "--prefix", relative,
                                     "--providers", "claude,muse"], cwd=self.base,
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rc = self.base / (".bashrc" if shell == "bash" else ".zshrc")
            result = subprocess.run([shell, "-c", 'source "$1"; claude-role minimal',
                                     "test", str(rc)], cwd="/", env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.base / "injected").exists())
        result = subprocess.run([str(ROOT / "uninstall.sh"), "--prefix", relative],
                                cwd=self.base, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for rc in (self.base / ".bashrc", self.base / ".zshrc"):
            if rc.exists():
                self.assertNotIn("mcp-roles", rc.read_text())


if __name__ == "__main__":
    unittest.main()
