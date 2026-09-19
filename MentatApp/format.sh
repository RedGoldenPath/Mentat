#!/bin/bash
# Format (or --lint) Swift sources with the Xcode toolchain's swift-format.
# The legacy monolith is intentionally left alone until it is rewritten; run this
# on the new files as they land, or pass explicit paths.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
SF="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift-format"
if [ ! -x "$SF" ]; then
  echo "format: swift-format not found in toolchain ($SF)" >&2
  exit 1
fi

CONFIG="$DIR/.swift-format"
MODE="format"
if [ "${1:-}" = "--lint" ]; then
  MODE="lint"
  shift
fi

PATHS=("$@")
if [ ${#PATHS[@]} -eq 0 ]; then
  PATHS=("$DIR/Sources")
fi

if [ "$MODE" = "lint" ]; then
  "$SF" lint --strict --configuration "$CONFIG" -r "${PATHS[@]}"
else
  "$SF" format --in-place --configuration "$CONFIG" -r "${PATHS[@]}"
fi
