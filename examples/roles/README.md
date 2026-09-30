# Example catalog

Each JSON file is a role. Its top-level `mcpServers` object maps server names to entries with either a `url` or `command`. Optional fields are `type`, `args`, `env`, `headers`, and `oauth`. The `oauth: true` hint maps to Hermes `auth: oauth`; other adapters remove it.

Use `${NAME}` in `url`, `command`, `args`, `env`, or `headers` for a required environment variable. The wrapper fails with the variable name if it is unset. For the `github`, `dev`, and `full` examples, export `GITHUB_PAT` before launch. The `minimal` role has no MCP servers.

The installer copies these examples into the catalog only when the catalog contains no JSON role files. Edit your installed catalog directly. Future installs leave existing roles untouched.
