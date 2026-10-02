#!/bin/bash
# UX verification gate: the test suite (surface/ink contrast invariants, token
# round-trips, slots, colour science, …) is the guard. Any failure blocks.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
fi
export DEVELOPER_DIR="${DEVELOPER_DIR:-}"
SWIFT=""
if [ -n "${DEVELOPER_DIR:-}" ]; then
  SWIFT="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift"
fi
[ -x "$SWIFT" ] || SWIFT="$(command -v swift || true)"
[ -x "$SWIFT" ] || { echo "verify: no Swift compiler" >&2; exit 1; }

echo "verify: invariants"
"$SWIFT" test 2>&1 | grep -E "error:|failed|Executed [0-9]+ tests" | tail -4
STATUS=${PIPESTATUS[0]}
[ "$STATUS" -eq 0 ] || { echo "verify: FAILED" >&2; exit 1; }

# Lean by construction: the sand is procedural, so the bundle ships no wallpaper
# art. If photo assets ever creep back in, the app balloons ~116 MB — block it.
if compgen -G "$DIR/Resources/bg-*.jpg" >/dev/null; then
  echo "verify: FAILED — bundled wallpaper art found (app must ship the procedural sand only)" >&2
  exit 1
fi
if [ -d "$DIR/Mentat.app" ]; then
  MB=$(du -sm "$DIR/Mentat.app" | cut -f1)
  echo "verify: bundle ${MB} MB"
  [ "$MB" -le 30 ] || { echo "verify: FAILED — bundle ${MB} MB > 30 MB cap" >&2; exit 1; }
fi
echo "verify: OK"
