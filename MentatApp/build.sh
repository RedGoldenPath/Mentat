#!/bin/bash
# Build the Mentat windowed app bundle (release) into Mentat.app.
#
# Targets macOS 27, so it needs the matching Xcode toolchain/SDK. Override with
# DEVELOPER_DIR=/path/to/Xcode.app/Contents/Developer if Xcode isn't at the
# default location.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/Mentat.app"

cd "$DIR"

# --- toolchain -------------------------------------------------------------
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
fi
export DEVELOPER_DIR="${DEVELOPER_DIR:-}"

SWIFT=""
if [ -n "${DEVELOPER_DIR:-}" ]; then
  SWIFT="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift"
fi
if [ ! -x "$SWIFT" ]; then SWIFT="$(command -v swift || true)"; fi
if [ -z "$SWIFT" ] || [ ! -x "$SWIFT" ]; then
  echo "build: no Swift compiler found — install Xcode or set DEVELOPER_DIR" >&2
  exit 1
fi

echo "build: $("$SWIFT" --version 2>/dev/null | head -1) [${DEVELOPER_DIR:-default toolchain}]"

# --- compile ---------------------------------------------------------------
BIN_DIR="$("$SWIFT" build -c release --show-bin-path)"
"$SWIFT" build -c release
BIN="$BIN_DIR/MentatApp"
[ -x "$BIN" ] || { echo "build: expected binary missing at $BIN" >&2; exit 1; }

# --- bundle ------------------------------------------------------------------
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/MentatApp"
[ -f "$DIR/AppIcon.icns" ] && cp "$DIR/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
if [ -d "$DIR/Resources" ]; then
  rm -f "$APP/Contents/Resources/"bg-*.jpg "$APP/Contents/Resources/"*.ttf
  find "$DIR/Resources" -maxdepth 1 -type f -exec cp {} "$APP/Contents/Resources/" \;
fi

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Mentat</string>
  <key>CFBundleDisplayName</key><string>Mentat</string>
  <key>CFBundleIdentifier</key><string>ai.mentat.app</string>
  <key>CFBundleExecutable</key><string>MentatApp</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleShortVersionString</key><string>0.3</string>
  <key>LSMinimumSystemVersion</key><string>27.0</string>
  <key>ATSApplicationFontsPath</key><string>.</string>
  <key>LSUIElement</key><false/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "Built $APP"
