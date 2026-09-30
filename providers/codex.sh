#!/usr/bin/env bash
# Source lib/core.sh before this adapter.

_codex_role_link_shared_state() {
    local real_dir="$1" runtime_dir="$2" name
    _mcp_roles_private_dirs "$runtime_dir" "$runtime_dir/log" "$runtime_dir/sessions" \
        "$runtime_dir/shell_snapshots" "$runtime_dir/tmp" "$runtime_dir/.tmp" || return 1
    # SQLite databases, including WAL and SHM sidecars, stay local.
    for name in auth.json cache history.jsonl installation_id memories \
        models_cache.json prompts rules skills version.json; do
        if [[ -e "$real_dir/$name" && ! -e "$runtime_dir/$name" && ! -L "$runtime_dir/$name" ]]; then
            ln -s "$real_dir/$name" "$runtime_dir/$name"
        fi
    done
}

_codex_role_write_config() {
    local role_json="$1" runtime_config="$2" base_config="$3" temp
    temp=$(mktemp "${runtime_config}.tmp.XXXXXX") || return 1
    chmod 600 "$temp"
    if [[ -f "$base_config" ]]; then
        # Parse TOML: table-looking text in multiline strings is not a table,
        # and quoted, indented, dotted and inline MCP definitions are all legal.
        if ! python3 - "$base_config" > "$temp" <<'PY'
import datetime
import json
import sys
try:
    import tomllib
except ImportError:
    raise SystemExit('Error: codex-role requires Python 3.11 or newer (tomllib).')

def value(item):
    if isinstance(item, str):
        return json.dumps(item, ensure_ascii=False)
    if isinstance(item, bool):
        return str(item).lower()
    if isinstance(item, (datetime.datetime, datetime.date, datetime.time)):
        return item.isoformat()
    if isinstance(item, (int, float)):
        return repr(item)
    if isinstance(item, list):
        return '[' + ', '.join(value(part) for part in item) + ']'
    if isinstance(item, dict):
        return '{' + ', '.join(value(key) + ' = ' + value(part)
                               for key, part in item.items()) + '}'
    raise ValueError(f'Unsupported TOML value: {type(item)}')

with open(sys.argv[1], 'rb') as source:
    config = tomllib.load(source)
config.pop('mcp_servers', None)
for key, item in config.items():
    print(value(key) + ' = ' + value(item))
PY
        then
            rm -f "$temp"
            return 1
        fi
    fi
    [[ ! -s "$temp" ]] || printf '\n' >> "$temp"
    if ! jq -r '
        def toml_value:
            if type == "string" then @json
            elif type == "array" then "[" + (map(toml_value) | join(", ")) + "]"
            elif type == "object" then
                "{" + (to_entries | map((.key | @json) + " = " + (.value | toml_value)) | join(", ")) + "}"
            elif type == "boolean" or type == "number" then tostring
            else error("unsupported TOML value type: " + type) end;
        .mcpServers | to_entries[] |
        "[mcp_servers." + (.key | @json) + "]\n" +
        (if .value.url then "url = " + (.value.url | toml_value) + "\n"
         else "command = " + (.value.command | toml_value) + "\n" end) +
        (if .value.args then "args = " + (.value.args | toml_value) + "\n" else "" end) +
        (if .value.env then "env = " + (.value.env | toml_value) + "\n" else "" end) +
        (if .value.headers then "http_headers = " + (.value.headers | toml_value) + "\n" else "" end) +
        "startup_timeout_sec = 10.0\ntool_timeout_sec = 60.0\n"
    ' "$role_json" >> "$temp"; then
        rm -f "$temp"
        return 1
    fi
    mv "$temp" "$runtime_config"
}

codex-role() (
    umask 077
    local role role_json base_dir runtime_home runtime_dir rendered flags=()
    _mcp_roles_parse "$@"
    role="$MCP_ROLES_ROLE"
    shift "$MCP_ROLES_CONSUMED"
    if [[ -z "$role" ]]; then
        _mcp_roles_help codex
        printf 'Login: codex-role <role> mcp login <server>\n'
        return 0
    fi
    role_json=$(_mcp_roles_role_file "$role") || return 1
    if [[ "${1:-}" == mcp && "${2:-}" == login && -n "${3:-}" ]]; then
        _mcp_roles_validate_login codex "$role" "$role_json" "$3" || return 1
    fi
    base_dir="$(_mcp_roles_account_home)/.codex"
    if [[ ! -d "$base_dir" ]]; then
        printf 'Error: %s not found. Run Codex once first.\n' "$base_dir" >&2
        return 1
    fi
    runtime_home="$base_dir/roles-runtime/$role"
    runtime_dir="$runtime_home/.codex"
    _mcp_roles_private_dirs "$base_dir/roles-runtime" "$runtime_home" "$runtime_dir" || return 1
    _codex_role_link_shared_state "$base_dir" "$runtime_dir" || return 1
    rendered="$runtime_dir/role.json"
    _mcp_roles_render "$role_json" "$rendered" || return 1
    _codex_role_write_config "$rendered" "$runtime_dir/config.toml" "$base_dir/config.toml" || return 1
    rm -f "$rendered"
    [[ "$MCP_ROLES_BYPASS_MODE" -eq 1 ]] && flags=(--dangerously-bypass-approvals-and-sandbox)
    _mcp_roles_announce Codex "$role" "$role_json" "$runtime_home" || return 1
    HOME="$runtime_home" CODEX_HOME="$runtime_dir" command "${MCP_ROLES_CODEX_BIN:-codex}" ${flags[@]+"${flags[@]}"} "$@"
)

_mcp_roles_register_completion codex-role
