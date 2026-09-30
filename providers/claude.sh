#!/usr/bin/env bash
# Source lib/core.sh before this adapter.

claude-role() (
    umask 077
    local role_json rendered role tempdir item placed=0 exit_code=0
    local flags=() args=()
    _mcp_roles_parse "$@"
    role="$MCP_ROLES_ROLE"
    shift "$MCP_ROLES_CONSUMED"
    if [[ -z "$role" ]]; then
        _mcp_roles_help claude
        return 0
    fi
    role_json=$(_mcp_roles_role_file "$role") || return 1
    tempdir=$(mktemp -d) || return 1
    trap 'rm -rf -- "$tempdir"' EXIT
    rendered="$tempdir/role.json"
    if ! _mcp_roles_render "$role_json" "$rendered"; then
        rm -rf "$tempdir"
        return 1
    fi
    [[ "$MCP_ROLES_BYPASS_MODE" -eq 1 ]] && flags=(--dangerously-skip-permissions)
    _mcp_roles_announce Claude "$role" "$role_json" || return 1
    # Last option, but still before -- so Claude parses it as configuration.
    for item in "$@"; do
        if [[ "$item" == -- && "$placed" -eq 0 ]]; then
            args+=(--mcp-config "$rendered")
            placed=1
        fi
        args+=("$item")
    done
    [[ "$placed" -eq 1 ]] || args+=(--mcp-config "$rendered")
    command "${MCP_ROLES_CLAUDE_BIN:-claude}" --strict-mcp-config ${flags[@]+"${flags[@]}"} ${args[@]+"${args[@]}"} || exit_code=$?
    return "$exit_code"
)

_mcp_roles_register_completion claude-role
