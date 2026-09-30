# mcp-roles

Define MCP server sets once and launch Claude Code, Codex, Hermes, or Muse with the set needed for a task. Smaller sets reduce tool clutter and the context spent describing unused tools. Each wrapper builds a role-specific runtime config without changing your main provider config.

## Quick start

Requires Bash 4 or newer or zsh, plus `jq`. Codex also requires Python 3.11 or newer; Hermes requires Mike Farah `yq` v4. Install the provider CLIs you intend to use.
Stock macOS `/bin/bash` is 3.2; install a newer Bash or use zsh. Ensure `~/.local/bin` is on your `PATH` (or log in again) to run `mcp-roles`.

```bash
./install.sh
source ~/.bashrc  # or ~/.zshrc
mcp-roles list
claude-role docs
```

The installer detects available provider binaries. To choose adapters explicitly:

```bash
./install.sh --providers claude,codex --prefix "$HOME/.local/share/mcp-roles"
```

It installs to `~/.local/share/mcp-roles`, adds one marked block to your bash or zsh rc file, and optionally links `mcp-roles` into `~/.local/bin` (use `--no-link-bin` to skip). It copies examples into the catalog only when no JSON roles exist there. Reinstalling updates code and the rc block without overwriting your roles. `./uninstall.sh` removes installed code and the rc block while leaving the catalog and provider runtimes.
Provider runtimes live under `~/.codex/roles-runtime/`, `~/.hermes/roles-runtime/`, and `~/.config/muse/roles-runtime/`; remove those directories manually when you no longer need their role-specific state.

The default catalog is `${XDG_CONFIG_HOME:-~/.config}/mcp-roles/roles`. Set `MCP_ROLES_DIR` to use another directory. `MCP_ROLES_BASE_HOME` overrides account-home lookup for testing or a custom profile root.

## Use

```bash
mcp-roles list
mcp-roles show docs
mcp-roles path
mcp-roles validate
mcp-roles doctor

claude-role browser --resume
codex-role docs
hermes-role notion mcp login notion
muse-role dev exec "Summarize this repository"
```

Wrappers use each provider's normal permission behavior by default. Put `--yolo` before or immediately after a role to request that provider's bypass flag. `MCP_ROLES_BYPASS=1` makes bypass the default; `--safe` overrides it for one invocation. Wrapper options placed later are passed to the provider. Explicit provider options still apply.

```bash
codex-role --yolo dev
claude-role dev --safe --resume
MCP_ROLES_BYPASS=1 muse-role --safe docs
```

The example `github`, `dev`, and `full` roles require `GITHUB_PAT`. Export it in the environment before launch. `minimal` deliberately has no MCP servers. `browser` starts Playwright through `npx`; Node.js and npm are needed when you use it.

## Role format

Every `*.json` file in the catalog defines a role:

```json
{
  "mcpServers": {
    "docs": {
      "type": "http",
      "url": "https://mcp.context7.com/mcp"
    },
    "browser": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"],
      "env": {"EXAMPLE_KEY": "${EXAMPLE_KEY}"}
    }
  }
}
```

Each server needs a `url` or `command`. The standard fields used by the adapters are `type`, `url`, `command`, `args`, `env`, and `headers`. Use `"oauth": true` for a server that requires Hermes OAuth; other adapters strip this hint. Unknown server keys are removed from runtime copies. `${VAR}` in `url`, `command`, `args`, `env`, and `headers` expands from the environment; an unset variable stops launch and is named in the error. Keep tokens in environment variables rather than role files.
Rendering `${VAR}` into private runtime copies keeps one role file usable across providers, including providers without a native token-environment setting.

The included roles are `minimal`, `browser`, `docs`, `github`, `notion`, `dev`, and `full`. See [example catalog](examples/roles/README.md).

## Provider behavior

| Adapter | Runtime | MCP rendering and state |
| --- | --- | --- |
| Claude | Temporary rendered JSON | Uses `--strict-mcp-config`; the variadic `--mcp-config` is last among Claude options, placed before a `--` end-of-options marker when present. |
| Codex | `~/.codex/roles-runtime/<role>/` | Parses base TOML, removes `mcp_servers`, adds role servers, and links selected shared state. SQLite databases and WAL/SHM files remain local to each role. Runs with `HOME=<runtime>` and `CODEX_HOME=<runtime>/.codex`, overriding an inherited `CODEX_HOME`. |
| Hermes | `~/.hermes/roles-runtime/<role>/` | Replaces `mcp_servers` in a copy of the base YAML. `oauth: true` becomes `auth: oauth`. Links credentials, skills, memories, and MCP tokens. Run Hermes setup first. |
| Muse | `~/.config/muse/roles-runtime/<role>/` | Merges base `settings.json` with role `mcpServers`; links `auth.json`, `trust.json`, and skills. Run Muse once first. |

Codex, Hermes, and Muse validate `mcp login <server>` against the selected role and suggest another role when the server is elsewhere. Use the same role catalog for all providers, but each provider keeps its own authentication format.

For a recognized Muse session subcommand, `--yolo` is appended at the end, or inserted immediately before `--` when one is present. Otherwise it is prepended. Muse removes duplicate `--yolo` options before `--`, preserving values of known options. The Muse `mcp` family receives no permission flag. Muse may also read a workspace `.mcp.json`; a workspace manifest with HTTP or SSE entries can disable its entire MCP subsystem, including role servers. Keep workspace manifests compatible with Muse.

Codex preserves base TOML values in the runtime copy; comments and formatting are not retained. Runtime directories use mode 0700 and rendered configuration files use 0600.

## Provider adapter contract

An adapter is a shell file in `providers/` sourced after `lib/core.sh`. Define `<provider>-role` with a subshell body (`<provider>-role() ( ... )`) to isolate variables and shell settings; call `_mcp_roles_parse "$@"`, shift `MCP_ROLES_CONSUMED`, and resolve the catalog file with `_mcp_roles_role_file`. Render via `_mcp_roles_render` into a private runtime copy, then translate that copy into provider settings. Preserve main user settings and isolate provider-specific mutable state. Call `_mcp_roles_validate_login` for an `mcp login` command, invoke the real binary through `command`, and register completion with `_mcp_roles_register_completion`. The selected binary may be overridden by `MCP_ROLES_<PROVIDER>_BIN` for testing.

## Troubleshooting

- Run `mcp-roles doctor` for missing tools, binaries, and catalog errors; `mcp-roles validate` checks every role file.
- If a wrapper is unavailable, source your rc file or source `lib/core.sh` followed by the desired adapter.
- If a role is missing, check `mcp-roles path` and `mcp-roles list`.
- If an environment variable is reported missing, export it before launch. The examples needing GitHub use `GITHUB_PAT`.
- If Codex, Hermes, or Muse reports missing base configuration, run that provider's normal setup once.
- For zsh completion, initialize `compinit` before sourcing the installer block.

See [SECURITY.md](SECURITY.md) for permission and token handling.
