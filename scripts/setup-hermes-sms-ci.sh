#!/usr/bin/env bash
# Install Hermes Agent + pinned telnyx-hermes-sms for sms-send-confirmed production-path tests.
set -euo pipefail

HERMES_CI_ROOT="${HERMES_CI_ROOT:-${TMPDIR:-/tmp}/hermes-sms-ci}"
HERMES_AGENT_REF="${HERMES_AGENT_REF:-c73cbcc4cbbdbfc7371a86287db1ff729f23837b}"
TELNYX_REF="${TELNYX_REF:-a7d209fbaedbbfa960d5bf3dda76b4e6477ce3d9}"

export HERMES_HOME="${HERMES_HOME:-$HERMES_CI_ROOT/hermes-home}"
mkdir -p "$HERMES_HOME/plugins"

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

python3 -m pip install --disable-pip-version-check -q -e "$HERMES_CI_ROOT/hermes-agent"
python3 -m pip install --disable-pip-version-check -q aiohttp

python3 - <<'PY'
from hermes_cli.plugins import discover_plugins
from gateway.platform_registry import platform_registry

discover_plugins()
platform_registry._resolve_all()
entry = platform_registry.get("telnyx_sms")
assert entry is not None and getattr(entry, "standalone_sender_fn", None), "telnyx_sms plugin not registered"
print("hermes-sms-ci: ok")
PY

touch "$HERMES_CI_ROOT/.ready"
