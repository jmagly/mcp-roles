#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/core.sh
source "$script_dir/lib/core.sh"
account_home=$(_mcp_roles_account_home)
prefix="$account_home/.local/share/mcp-roles"
if [[ "${1:-}" == --prefix && -n "${2:-}" && "$#" -eq 2 ]]; then
    prefix="$2"
elif [[ "$#" -ne 0 ]]; then
    printf 'Usage: uninstall.sh [--prefix DIR]\n' >&2
    exit 2
fi
if [[ -d "$prefix" ]]; then prefix=$(cd "$prefix" && pwd -P); fi

for rc in "$account_home/.bashrc" "$account_home/.zshrc"; do
    [[ -f "$rc" ]] || continue
    rc_temp=$(mktemp "${rc}.tmp.XXXXXX")
    if ! _mcp_roles_strip_rc_block "$rc" "$(printf 'source %q' "$prefix/init.sh")" > "$rc_temp"; then
        rm -f "$rc_temp"
        exit 1
    fi
    cat "$rc_temp" > "$rc"
    rm -f "$rc_temp"
done

bin_link="$account_home/.local/bin/mcp-roles"
if [[ -L "$bin_link" && "$(readlink "$bin_link")" == "$prefix/bin/mcp-roles" ]]; then
    rm -f "$bin_link"
fi
if [[ -f "$prefix/.mcp-roles-install" ]]; then
    # A prefix may contain a custom catalog or unrelated user files. Remove
    # only files this installer owns; rmdir preserves any nonempty directory.
    for installed_file in lib/core.sh providers/claude.sh providers/codex.sh \
        providers/hermes.sh providers/muse.sh bin/mcp-roles init.sh .mcp-roles-install; do
        rm -f -- "$prefix/$installed_file"
    done
    rmdir "$prefix/lib" "$prefix/providers" "$prefix/bin" "$prefix" 2>/dev/null || true
    printf 'Removed installation: %s\n' "$prefix"
else
    printf 'No marked installation at %s\n' "$prefix"
fi
printf 'Left catalog: %s\n' "$(_mcp_roles_catalog_dir)"
printf 'Left provider role runtimes under .codex, .hermes, and .config/muse in %s\n' "$account_home"
