#!/bin/bash
# Build the standalone Sand Lab window (separate from the Mentat app).
# Compiles Shaders.metal -> default.metallib (via the Metal Toolchain) and
# bundles it so ShaderLibrary.default can find it.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/SandLab.app"

if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
fi
export DEVELOPER_DIR="${DEVELOPER_DIR:-}"
SWIFT="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift"
[ -x "$SWIFT" ] || SWIFT="$(command -v swift)"

cd "$DIR"
mkdir -p "$DIR/.build"
echo "build: compiling the shared SandCore shader…"
# The lab and the app both compile the *same* SandCore shader, so anything tuned
# here is the code that ships.
SAND_METAL="$DIR/../SandCore/Sources/SandCore/SandShaders.metal"
[ -f "$SAND_METAL" ] || { echo "build: missing $SAND_METAL" >&2; exit 1; }
xcrun -sdk macosx metal -c "$SAND_METAL" -o "$DIR/.build/sand.air"
xcrun -sdk macosx metallib "$DIR/.build/sand.air" -o "$DIR/.build/default.metallib"

echo "build: compiling Swift…"
BIN_DIR="$("$SWIFT" build -c release --show-bin-path)"
"$SWIFT" build -c release
BIN="$BIN_DIR/SandLab"
[ -x "$BIN" ] || { echo "build: binary missing at $BIN" >&2; exit 1; }

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/SandLab"
cp "$DIR/.build/default.metallib" "$APP/Contents/Resources/default.metallib"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>SandLab</string>
  <key>CFBundleDisplayName</key><string>Sand Lab</string>
  <key>CFBundleIdentifier</key><string>ai.mentat.sandlab</string>
  <key>CFBundleExecutable</key><string>SandLab</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>LSMinimumSystemVersion</key><string>27.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "Built $APP"
