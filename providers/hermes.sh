#!/usr/bin/env bash
# Source lib/core.sh before this adapter.

_hermes_role_link_shared_state() {
    local base_dir="$1" runtime_dir="$2" name
    _mcp_roles_private_dirs "$runtime_dir" "$base_dir/mcp-tokens" "$runtime_dir/logs" "$runtime_dir/sessions" || return 1
    for name in .env SOUL.md auth.json auth.lock skills memories mcp-tokens; do
        if [[ -e "$base_dir/$name" && ! -e "$runtime_dir/$name" && ! -L "$runtime_dir/$name" ]]; then
            ln -s "$base_dir/$name" "$runtime_dir/$name"
        fi
    done
}

_hermes_role_write_config() {
    local role_json="$1" runtime_config="$2" base_config="$3" temp servers
    if ! command -v yq >/dev/null 2>&1; then
        printf 'Error: hermes-role requires yq v4.\n' >&2
        return 1
    fi
    if [[ ! -f "$base_config" ]]; then
        printf 'Error: %s not found. Run Hermes setup first.\n' "$base_config" >&2
        return 1
    fi
    temp=$(mktemp "${runtime_config}.tmp.XXXXXX") || return 1
    servers=$(mktemp "${runtime_config}.servers.XXXXXX") || { rm -f "$temp"; return 1; }
    chmod 600 "$temp"
    chmod 600 "$servers"
    # shellcheck disable=SC2016 # yq expression uses its own variables.
    if ! yq -p=json -oy '.mcpServers | with_entries(
        .value |= ((.oauth == true) as $oauth |
            del(.type, .oauth) | with(select($oauth); .auth = "oauth"))
    )' "$role_json" > "$servers"; then
        rm -f "$temp" "$servers"
        return 1
    fi
    # shellcheck disable=SC2016 # yq expression uses its own variables.
    if ! yq eval-all '
        select(fileIndex == 0) as $base |
        select(fileIndex == 1) as $servers |
        $base | .mcp_servers = $servers
    ' "$base_config" "$servers" > "$temp"; then
        rm -f "$temp" "$servers"
        return 1
    fi
    rm -f "$servers"
    mv "$temp" "$runtime_config"
}

hermes-role() (
    umask 077
    local role role_json base_dir runtime_home rendered flags=()
    _mcp_roles_parse "$@"
    role="$MCP_ROLES_ROLE"
    shift "$MCP_ROLES_CONSUMED"
    if [[ -z "$role" ]]; then
        _mcp_roles_help hermes
        printf 'Login: hermes-role <role> mcp login <server>\n'
        return 0
    fi
    role_json=$(_mcp_roles_role_file "$role") || return 1
    if [[ "${1:-}" == mcp && "${2:-}" == login && -n "${3:-}" ]]; then
        _mcp_roles_validate_login hermes "$role" "$role_json" "$3" || return 1
    fi
    base_dir="$(_mcp_roles_account_home)/.hermes"
    runtime_home="$base_dir/roles-runtime/$role"
    _mcp_roles_private_dirs "$base_dir/roles-runtime" "$runtime_home" || return 1
    _hermes_role_link_shared_state "$base_dir" "$runtime_home" || return 1
    rendered="$runtime_home/role.json"
    _mcp_roles_render "$role_json" "$rendered" true || return 1
    _hermes_role_write_config "$rendered" "$runtime_home/config.yaml" "$base_dir/config.yaml" || return 1
    rm -f "$rendered"
    [[ "$MCP_ROLES_BYPASS_MODE" -eq 1 ]] && flags=(--yolo)
    _mcp_roles_announce Hermes "$role" "$role_json" "$runtime_home" || return 1
    HERMES_HOME="$runtime_home" command "${MCP_ROLES_HERMES_BIN:-hermes}" ${flags[@]+"${flags[@]}"} "$@"
)

_mcp_roles_register_completion hermes-role
