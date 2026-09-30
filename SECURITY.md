# Security

Role wrappers use each provider's normal permission behavior unless you opt in to bypass with `--yolo` or `MCP_ROLES_BYPASS=1`. `--safe` disables the wrapper's automatic bypass flag for that launch. Provider settings and explicit arguments can still affect permissions.

Codex, Hermes, and Muse role runtimes link selected authentication and other state from the main profile. A token or login may therefore be available across roles that use the same provider. Restrict access to your profile and revoke credentials through the provider when needed.

Never commit secrets to role JSON. Use `${VAR}` placeholders and export values at launch. Rendered runtime configs can contain expanded credentials; keep runtime directories private and remove them when no longer needed. Report security issues privately to the maintainer through GitHub's security advisory channel.
