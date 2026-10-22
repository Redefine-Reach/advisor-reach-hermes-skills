#!/usr/bin/env bash
# Install Hermes Agent + pinned telnyx-hermes-sms for sms-send-confirmed production-path tests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_FILE="$SCRIPT_DIR/hermes-ci-source.txt"
# Pin recorded in scripts/hermes-ci-source.txt (sms-box image digest + git commit).
HERMES_AGENT_REF="${HERMES_AGENT_REF:-$(grep '^HERMES_AGENT_REF=' "$SOURCE_FILE" | cut -d= -f2-)}"
TELNYX_REF="${TELNYX_REF:-$(grep '^TELNYX_HERMES_SMS_REF=' "$SOURCE_FILE" | cut -d= -f2-)}"
HERMES_CI_PYTHON="${HERMES_CI_PYTHON:-$(grep '^HERMES_CI_PYTHON=' "$SOURCE_FILE" | cut -d= -f2-)}"

HERMES_CI_ROOT="${HERMES_CI_ROOT:-${TMPDIR:-/tmp}/hermes-sms-ci}"
export HERMES_HOME="${HERMES_HOME:-$HERMES_CI_ROOT/hermes-home}"
mkdir -p "$HERMES_HOME/plugins"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [ ! -d "$HERMES_CI_ROOT/hermes-agent/.git" ]; then
  git clone https://github.com/NousResearch/hermes-agent.git "$HERMES_CI_ROOT/hermes-agent"
fi
git -C "$HERMES_CI_ROOT/hermes-agent" fetch origin "$HERMES_AGENT_REF" --depth 1 2>/dev/null || \
  git -C "$HERMES_CI_ROOT/hermes-agent" fetch origin "$HERMES_AGENT_REF"
git -C "$HERMES_CI_ROOT/hermes-agent" checkout --force "$HERMES_AGENT_REF"

if [ ! -d "$HERMES_HOME/plugins/telnyx_sms/.git" ]; then
  git clone https://github.com/team-telnyx/telnyx-hermes-sms.git "$HERMES_HOME/plugins/telnyx_sms"
fi
git -C "$HERMES_HOME/plugins/telnyx_sms" fetch origin "$TELNYX_REF" --depth 1 2>/dev/null || \
  git -C "$HERMES_HOME/plugins/telnyx_sms" fetch origin "$TELNYX_REF"
git -C "$HERMES_HOME/plugins/telnyx_sms" checkout --force "$TELNYX_REF"

cat >"$HERMES_HOME/config.yaml" <<'EOF'
plugins:
  enabled:
    - telnyx_sms
    - telnyx-sms-platform
EOF

export UV_PYTHON="${UV_PYTHON:-$HERMES_CI_PYTHON}"
uv sync --frozen --project "$HERMES_CI_ROOT/hermes-agent"

VENV_PYTHON="$HERMES_CI_ROOT/hermes-agent/.venv/bin/python"
uv pip install --python "$VENV_PYTHON" \
  -e "$HERMES_HOME/plugins/telnyx_sms" \
  -c "$SCRIPT_DIR/hermes-ci-constraints.txt"

SITE_PACKAGES="$("$VENV_PYTHON" -c "import site; print(site.getsitepackages()[0])")"
cp "$REPO_ROOT/tests/sms_send_socket_guard.py" "$SITE_PACKAGES/"
printf '%s\n' "import sms_send_socket_guard" >"$SITE_PACKAGES/sms_send_ci_guard.pth"

HERMES_HOME="$HERMES_HOME" "$VENV_PYTHON" - <<'PY'
from hermes_cli.plugins import discover_plugins
from gateway.platform_registry import platform_registry

discover_plugins()
platform_registry._resolve_all()
entry = platform_registry.get("telnyx_sms")
assert entry is not None and getattr(entry, "standalone_sender_fn", None), "telnyx_sms plugin not registered"
print("hermes-sms-ci: ok")
PY

printf '%s\n' "$VENV_PYTHON" >"$HERMES_CI_ROOT/.python"
touch "$HERMES_CI_ROOT/.ready"
