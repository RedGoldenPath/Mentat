#!/bin/zsh
# M4 — fuse the LoRA adapter into the base and import it into Ollama.
# Usage: ./import_model.sh [adapter_path] [ollama_name]
set -e
cd "$(dirname "$0")"

ADAPTER=${1:-adapters/mentat-v1}
NAME=${2:-mentat-local}
FUSED=models/mentat-fused

echo "== fuse (dequantized f16 for export) =="
.venv/bin/mlx_lm.fuse \
  --model models/qwen3.8-27b-4bit \
  --adapter-path "$ADAPTER" \
  --save-path "$FUSED" \
  --dequantize

echo "== import into Ollama ($NAME, q4_K_M) =="
MF=$(mktemp /tmp/Modelfile.mentat.XXXXXX)
cat > "$MF" <<EOF
FROM $PWD/$FUSED
EOF
if ! ollama create "$NAME" --quantize q4_K_M --experimental -f "$MF"; then
  echo "safetensors import refused — falling back to GGUF f16 + native quantize"
  .venv/bin/mlx_lm.fuse \
    --model models/qwen3.8-27b-4bit \
    --adapter-path "$ADAPTER" \
    --save-path "$FUSED" \
    --dequantize --export-gguf --gguf-path "$FUSED/mentat-v1-f16.gguf"
  cat > "$MF" <<EOF
FROM $FUSED/mentat-v1-f16.gguf
EOF
  ollama create "$NAME" --quantize q4_K_M -f "$MF"
fi
rm -f "$MF"

echo "== done =="
ollama show "$NAME" | head -14
