# Contributing

Issues and pull requests are welcome. Keep roles provider-neutral, examples public, and runtime state isolated. Add a focused unittest for behavior changes. Run:

```bash
shellcheck -x install.sh uninstall.sh bin/mcp-roles lib/*.sh providers/*.sh
python3 -m unittest discover -s tests -v
```

Do not commit tokens, private endpoints, or generated runtime files.
