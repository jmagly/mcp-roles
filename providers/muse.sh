#!/usr/bin/env bash
# Source lib/core.sh before this adapter.

_muse_role_is_session_subcommand() {
    case "${1:-}" in
        resume|exec|config|export|trace|skills|plugins|sandbox|schema|serve|\
        session-message|auth|login|logout|init) return 0 ;;
        *) return 1 ;;
    esac
}

_muse_role_link_shared_state() {
    local base_dir="$1" runtime_dir="$2" name
    _mcp_roles_private_dirs "$base_dir/roles-runtime" "$runtime_dir" "$runtime_dir/muse" || return 1
    for name in auth.json trust.json skills; do
        if [[ -e "$base_dir/$name" && ! -e "$runtime_dir/muse/$name" && ! -L "$runtime_dir/muse/$name" ]]; then
            ln -s "$base_dir/$name" "$runtime_dir/muse/$name"
        fi
    done
}

_muse_role_write_config() {
    local role_json="$1" runtime_config="$2" base_config="$3" temp
    temp=$(mktemp "${runtime_config}.tmp.XXXXXX") || return 1
    chmod 600 "$temp"
    if [[ -f "$base_config" ]]; then
        if ! jq --slurpfile role "$role_json" 'del(.mcpServers) * {mcpServers: $role[0].mcpServers}' "$base_config" > "$temp"; then
            rm -f "$temp"
            return 1
        fi
    elif ! jq --slurpfile role "$role_json" -n '{schema_version: 1, mcpServers: $role[0].mcpServers}' > "$temp"; then
        rm -f "$temp"
        return 1
    fi
    mv "$temp" "$runtime_config"
}

muse-role() (
    umask 077
    local role role_json base_dir runtime_home rendered item first=''
    local bypass user_yolo=0 seen_dashdash=0 placed=0 expect_value=0 have_first=0
    local args=() final=()
    _mcp_roles_parse "$@"
    role="$MCP_ROLES_ROLE"
    bypass="$MCP_ROLES_BYPASS_MODE"
    shift "$MCP_ROLES_CONSUMED"
    if [[ -z "$role" ]]; then
        _mcp_roles_help muse
        printf 'Login: muse-role <role> mcp login <server>\n'
        return 0
    fi
    role_json=$(_mcp_roles_role_file "$role") || return 1
    if [[ "${1:-}" == mcp && "${2:-}" == login && -n "${3:-}" ]]; then
        _mcp_roles_validate_login muse "$role" "$role_json" "$3" || return 1
    fi
    base_dir="$(_mcp_roles_account_home)/.config/muse"
    if [[ ! -d "$base_dir" ]]; then
        printf 'Error: %s not found. Run Muse once first.\n' "$base_dir" >&2
        return 1
    fi
    runtime_home="$base_dir/roles-runtime/$role"
    _muse_role_link_shared_state "$base_dir" "$runtime_home" || return 1
    rendered="$runtime_home/muse/role.json"
    _mcp_roles_render "$role_json" "$rendered" || return 1
    _muse_role_write_config "$rendered" "$runtime_home/muse/settings.json" "$base_dir/settings.json" || return 1
    rm -f "$rendered"

    # Explicit provider --yolo is deduplicated, except after -- where it is data.
    for item in "$@"; do
        if [[ "$expect_value" -eq 1 ]]; then
            expect_value=0
        elif [[ "$item" == -- && "$seen_dashdash" -eq 0 ]]; then
            seen_dashdash=1
        elif [[ "$item" == --yolo && "$seen_dashdash" -eq 0 ]]; then
            user_yolo=1
            continue
        elif [[ "$seen_dashdash" -eq 0 ]]; then
            # Values are opaque, including values spelled --safe or --yolo.
            case "$item" in
                -p|--prompt|--agents|--provider|--preset|--model|--reasoning-effort|\
                --base-url|--image|--workspace|--worktree-base|--worktree-existing|\
                --approval-mode|--permission-profile|--approval-judge|--echo-delay-ms|\
                --sandbox-network) expect_value=1 ;;
            esac
        fi
        if [[ "$have_first" -eq 0 ]]; then first="$item"; have_first=1; fi
        args+=("$item")
    done
    [[ "$user_yolo" -eq 1 ]] && bypass=1
    [[ "$first" == mcp ]] && bypass=0

    if [[ "$bypass" -eq 1 ]] && _muse_role_is_session_subcommand "$first"; then
        for item in ${args[@]+"${args[@]}"}; do
            if [[ "$item" == -- && "$placed" -eq 0 ]]; then
                final+=(--yolo)
                placed=1
            fi
            final+=("$item")
        done
        [[ "$placed" -eq 1 ]] || final+=(--yolo)
    elif [[ "$bypass" -eq 1 ]]; then
        final=(--yolo ${args[@]+"${args[@]}"})
    else
        final=(${args[@]+"${args[@]}"})
    fi
    _mcp_roles_announce Muse "$role" "$role_json" "$runtime_home" || return 1
    XDG_CONFIG_HOME="$runtime_home" command "${MCP_ROLES_MUSE_BIN:-muse}" ${final[@]+"${final[@]}"}
)

_mcp_roles_register_completion muse-role
