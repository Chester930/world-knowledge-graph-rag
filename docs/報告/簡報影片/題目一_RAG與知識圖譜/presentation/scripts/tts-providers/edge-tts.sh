#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# edge-tts.sh — Microsoft Edge free TTS provider adapter.
#
# Requires: pip install edge-tts
# ────────────────────────────────────────────────────────────────────

tts_check() {
  if ! command -v edge-tts >/dev/null; then
    echo "✗ 'edge-tts' command not found." >&2
    echo "  Please install it via pip:" >&2
    echo "    pip install edge-tts" >&2
    return 1
  fi
  return 0
}

tts_install_help() {
  echo "安裝指南:"
  echo "  pip install edge-tts"
}

tts_synthesize() {
  local text="$1"
  local out_path="$2"
  local voice="${3:-zh-TW-YunJheNeural}" # Default voice: Taiwanese Mandarin YunJhe (Male)
  
  # Execute edge-tts CLI
  edge-tts --voice "$voice" --text "$text" --write-media "$out_path"
}
