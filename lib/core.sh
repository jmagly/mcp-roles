#!/usr/bin/env bash
# Shared catalog and argument helpers. Source before a provider adapter.
if [[ -z "${ZSH_VERSION:-}" && "${BASH_VERSINFO[0]:-0}" -lt 4 ]]; then
    printf 'Error: bash 4+ or zsh required (macOS: brew install bash).\n' >&2
    # shellcheck disable=SC2317 # exit handles direct execution; return handles sourcing.
    return 1 2>/dev/null || exit 1
fi

_mcp_roles_account_home() {
    local account_home=''
    if [[ -n "${MCP_ROLES_BASE_HOME:-}" ]]; then
        printf '%s\n' "$MCP_ROLES_BASE_HOME"
        return
    fi
    if command -v getent >/dev/null 2>&1; then
        account_home=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6)
    fi
    if [[ -z "$account_home" ]] && command -v dscl >/dev/null 2>&1; then
        account_home=$(dscl . -read "/Users/$(id -un)" NFSHomeDirectory 2>/dev/null | awk 'NR == 1 {print $2}')
    fi
    if [[ -z "$account_home" ]]; then
        account_home=$(printf '%s\n' ~)
    fi
    printf '%s\n' "${account_home:-$HOME}"
}

_mcp_roles_catalog_dir() {
    if [[ -n "${MCP_ROLES_DIR:-}" ]]; then
        printf '%s\n' "$MCP_ROLES_DIR"
    elif [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
        printf '%s/mcp-roles/roles\n' "$XDG_CONFIG_HOME"
    else
        printf '%s/.config/mcp-roles/roles\n' "$(_mcp_roles_account_home)"
    fi
}

_mcp_roles_list_names() {
    [[ -z "${ZSH_VERSION:-}" ]] || setopt localoptions nonomatch
    local f dir
    dir=$(_mcp_roles_catalog_dir)
    for f in "$dir"/*.json; do
        [[ -f "$f" ]] || continue
        f=${f##*/}
        printf '%s\n' "${f%.json}"
    done
}

_mcp_roles_role_file() {
    local role="$1" dir
    if [[ ! "$role" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]]; then
        printf "Error: Invalid role name '%s'.\n" "$role" >&2
        return 1
    fi
    dir=$(_mcp_roles_catalog_dir)
    if [[ ! -f "$dir/$role.json" ]]; then
        printf "Error: Role '%s' not found. Available roles: " "$role" >&2
        _mcp_roles_list_names | tr '\n' ' ' >&2
        printf '\n' >&2
        return 1
    fi
    printf '%s\n' "$dir/$role.json"
}

_mcp_roles_roles_for_server() {
    [[ -z "${ZSH_VERSION:-}" ]] || setopt localoptions nonomatch
    local server="$1" f
    local matches=()
    for f in "$(_mcp_roles_catalog_dir)"/*.json; do
        [[ -f "$f" ]] || continue
        if jq -e --arg server "$server" '.mcpServers[$server] != null' "$f" >/dev/null 2>&1; then
            f=${f##*/}
            matches+=("${f%.json}")
        fi
    done
    printf '%s\n' "${matches[*]}"
}

_mcp_roles_validate_login() {
    local provider="$1" role="$2" role_json="$3" server="$4" matches
    if jq -e --arg server "$server" '.mcpServers[$server] != null' "$role_json" >/dev/null 2>&1; then
        return 0
    fi
    matches=$(_mcp_roles_roles_for_server "$server")
    printf "Error: MCP server '%s' is not part of role '%s'.\n" "$server" "$role" >&2
    if [[ -n "$matches" ]]; then
        printf 'Available in role(s): %s\n' "$matches" >&2
        printf 'Try: %s-role %s mcp login %s\n' "$provider" "${matches%% *}" "$server" >&2
    else
        printf "No role contains MCP server '%s'.\n" "$server" >&2
    fi
    return 1
}

_mcp_roles_validate_file() {
    jq -e 'type == "object" and (.mcpServers | type == "object")
        and (.mcpServers | all(.[]; type == "object" and
            ((.url | type == "string") or (.command | type == "string"))))' "$1" >/dev/null
}

# Output contains only standard keys, plus oauth when explicitly requested for Hermes.
# Expansion applies to values in url/command/args/env/headers. Missing variables fail.
_mcp_roles_render() {
    local source="$1" output="$2" keep_oauth="${3:-false}" temp
    _mcp_roles_validate_file "$source" || {
        printf 'Error: Invalid role file: %s\n' "$source" >&2
        return 1
    }
    temp=$(mktemp "${output}.tmp.XXXXXX") || return 1
    chmod 600 "$temp"
    if ! jq --argjson keep_oauth "$keep_oauth" '
        def expand:
            if type == "string" then
                gsub("\\$\\{(?<name>[A-Za-z_][A-Za-z0-9_]*)\\}";
                    env[.name] // error("Environment variable " + .name + " is not set"))
            elif type == "array" then map(expand)
            elif type == "object" then with_entries(.value |= expand)
            else . end;
        {mcpServers: (.mcpServers | with_entries(
            .value |= (with_entries(select(
                .key as $key |
                (["type", "url", "command", "args", "env", "headers"] +
                 (if $keep_oauth then ["oauth"] else [] end)) | index($key)
            )) |
            .url |= (if . == null then empty else expand end) |
            .command |= (if . == null then empty else expand end) |
            .args |= (if . == null then empty else expand end) |
            .env |= (if . == null then empty else expand end) |
            .headers |= (if . == null then empty else expand end))
        ))}
    ' "$source" > "$temp"; then
        rm -f "$temp"
        return 1
    fi
    mv "$temp" "$output"
}

# Called inside a wrapper subshell; leave provider arguments untouched beyond consumed prefix.
# shellcheck disable=SC2034 # Outputs are globals consumed by sourced adapters.
_mcp_roles_parse() {
    MCP_ROLES_ROLE=''
    MCP_ROLES_CONSUMED=0
    MCP_ROLES_BYPASS_MODE=0
    [[ "${MCP_ROLES_BYPASS:-0}" == 1 ]] && MCP_ROLES_BYPASS_MODE=1
    while [[ "${1:-}" == --safe || "${1:-}" == --yolo ]]; do
        [[ "$1" == --safe ]] && MCP_ROLES_BYPASS_MODE=0 || MCP_ROLES_BYPASS_MODE=1
        shift
        MCP_ROLES_CONSUMED=$((MCP_ROLES_CONSUMED + 1))
    done
    if [[ -n "${1:-}" ]]; then
        MCP_ROLES_ROLE="$1"
        shift
        MCP_ROLES_CONSUMED=$((MCP_ROLES_CONSUMED + 1))
    fi
    while [[ "${1:-}" == --safe || "${1:-}" == --yolo ]]; do
        [[ "$1" == --safe ]] && MCP_ROLES_BYPASS_MODE=0 || MCP_ROLES_BYPASS_MODE=1
        shift
        MCP_ROLES_CONSUMED=$((MCP_ROLES_CONSUMED + 1))
    done
}

# Limit newly created parents too, without changing the interactive shell's umask.
_mcp_roles_private_dirs() (
    umask 077
    for directory in "$@"; do
        if [[ -L "$directory" ]]; then
            printf 'Error: Runtime directory is a symlink: %s\n' "$directory" >&2
            return 1
        fi
    done
    mkdir -p -- "$@" && chmod 700 -- "$@"
)

# Reject malformed markers before callers replace the rc file. On uninstall,
# remove only the block for the requested prefix, preserving other installs.
_mcp_roles_strip_rc_block() {
    MCP_ROLES_RC_SOURCE="${2:-}" awk '
        BEGIN {target=ENVIRON["MCP_ROLES_RC_SOURCE"]}
        $0 == "# >>> mcp-roles >>>" {
            if (inside) {bad=1; exit}
            inside=1; block=$0 ORS; matches=0; next
        }
        $0 == "# <<< mcp-roles <<<" {
            if (!inside) {bad=1; exit}
            if (target != "" && !matches) printf "%s%s\n", block, $0
            inside=0; next
        }
        inside {block=block $0 ORS; if ($0 == target) matches=1; next}
        {print}
        END {if (inside || bad) exit 1}
    ' "$1" || {
        printf 'Error: Malformed mcp-roles rc block in %s; file left unchanged.\n' "$1" >&2
        return 1
    }
}

_mcp_roles_help() {
    local provider="$1"
    printf 'Usage: %s-role [--safe|--yolo] <role> [--safe|--yolo] [%s args...]\n' "$provider" "$provider"
    printf 'Safe by default. MCP_ROLES_BYPASS=1 enables bypass by default.\n'
    printf 'Available roles:\n'
    _mcp_roles_list_names
}

_mcp_roles_announce() {
    local provider="$1" role="$2" role_json="$3" runtime="${4:-}" servers
    servers=$(jq -r '.mcpServers | keys | join(", ")' "$role_json") || return 1
    printf 'Starting %s with role: %s\n' "$provider" "$role"
    [[ -z "$runtime" ]] || printf 'Runtime home: %s\n' "$runtime"
    printf 'MCPs: %s\n---\n' "$servers"
}

_mcp_roles_complete_bash() {
    local cur="${COMP_WORDS[COMP_CWORD]}" roles
    COMPREPLY=()
    if [[ "$COMP_CWORD" -eq 1 ]] || [[ "$COMP_CWORD" -eq 2 && "${COMP_WORDS[1]}" == --* ]]; then
        roles=$(_mcp_roles_list_names)
        # shellcheck disable=SC2207 # compgen produces one completion per line.
        COMPREPLY=($(compgen -W "$roles --safe --yolo" -- "$cur"))
    fi
}

_mcp_roles_complete_zsh() {
    local role
    local -a roles
    roles=()
    while IFS= read -r role; do
        roles+=("$role")
    done < <(_mcp_roles_list_names)
    _describe 'role' roles
}

_mcp_roles_register_completion() {
    local command_name="$1"
    if [[ -n "${BASH_VERSION:-}" ]]; then
        complete -F _mcp_roles_complete_bash "$command_name"
    elif [[ -n "${ZSH_VERSION:-}" ]] && command -v compdef >/dev/null 2>&1; then
        compdef _mcp_roles_complete_zsh "$command_name"
    fi
}
