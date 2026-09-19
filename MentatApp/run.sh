#!/bin/bash
# Launch the Mentat app. The Python engine is app-owned (EngineProcess starts it
# on 127.0.0.1:8765), so this only builds the bundle and opens it.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/Mentat.app"

"$DIR/build.sh"
open "$APP"
