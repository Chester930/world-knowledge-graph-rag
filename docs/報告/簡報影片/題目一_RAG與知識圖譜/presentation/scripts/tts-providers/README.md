# TTS Providers

`synthesize-audio.sh` 是 provider-agnostic 的 runner —— 它自己不知道
怎麼調任何 TTS，只知道循環 `audio-segments.json`、跳過已存在文件、
打印進度。

**每個 provider 是這個目錄下的一個 `.sh` 文件**，定義一個
`tts_synthesize` 函數（必需），以及可選的 `tts_check` 和
`tts_install_help`。runner 根據 `PRESENTATION_TTS` 環境變量加載對應文件。

---

## 怎麼用

```bash
# 默認（minimax）
npm run synthesize-audio

# 換 provider
PRESENTATION_TTS=openai npm run synthesize-audio
npm run synthesize-audio -- --provider=elevenlabs

# 指定音色（每個 provider 自己解析）
PRESENTATION_TTS_VOICE=alloy npm run synthesize-audio
npm run synthesize-audio -- --voice=zh-CN-YunxiNeural

# 強制全部重合成
npm run synthesize-audio -- --force
```

`--provider` 和 `--voice` 的命令行參數會覆蓋 env var。

---

## 內置 provider

| 文件 | 後端 | 鑑權 | 備註 |
|---|---|---|---|
| `minimax.sh` | MiniMax `mmx` CLI | `mmx auth login --api-key` | **默認**；中文口播質量穩 |
| `openai.sh` | OpenAI Audio Speech API | `OPENAI_API_KEY` env var | curl-based；多數 agent 已有 key |

只內置這兩個 —— 我們不替你做更多技術選型。其它後端的代碼片段在下面，
複製到 `tts-providers/<name>.sh` 即可啓用。

---

## 怎麼加你自己的 TTS

1. 在這個目錄建 `<name>.sh`（小寫、kebab-case）
2. 實現 `tts_synthesize text out_path [voice]`（必需）
3. 可選實現 `tts_check`（啓動前校驗環境）和 `tts_install_help`（失敗時打印怎麼修）
4. `PRESENTATION_TTS=<name> npm run synthesize-audio`

---

## 三函數契約

### `tts_synthesize <text> <out_path> [<voice>]` （required）

把一段文字寫成 mp3 / 任意 web 可播的音頻文件到 `<out_path>`。

| 參數 | 說明 |
|---|---|
| `$1` | 要合成的文本（已是 UTF-8 字符串，可能包含中英文混排和標點） |
| `$2` | 目標文件絕對路徑（runner 已 `mkdir -p` 它的父目錄），擴展名 `.mp3` |
| `$3` | 音色 id（可能爲空字符串，provider 自行決定默認） |

成功 → exit 0 並把音頻寫到 `$2`。失敗 → 非零退出（runner 會標 FAILED 繼續下一段，不會終止全局合成）。

> 如果 backend 只能出 wav / ogg，自己在函數末尾用 `ffmpeg` 轉一下：
> `ffmpeg -y -i tmp.wav -codec:a libmp3lame -qscale:a 2 "$out" >/dev/null 2>&1`

### `tts_check` （optional）

啓動時被 runner 調一次（不是每段）。檢查 CLI 是否裝、API key 是否設、auth 是否通。
未就緒 return 非零，runner 會立刻終止並打印 `tts_install_help`。

### `tts_install_help` （optional）

`tts_check` 失敗時被 runner 調，往 stderr 打印怎麼裝 / 怎麼登錄 / 在哪拿 key。

---

## 常見 TTS 後端的現成片段

下面**不是**內置 provider —— 是你自己寫 `tts-providers/<name>.sh` 時
可以**直接抄過去**的代碼片段。複製 → 保存爲 `<name>.sh` → 調通了
就 `PRESENTATION_TTS=<name>` 用。

> 大多數雲 TTS 的 API key 通過環境變量傳入（例如 `OPENAI_API_KEY`、
> `ELEVENLABS_API_KEY`）。把 `export` 加到你的 shell rc，或在
> 同目錄放一個 git-ignored 的 `.env` 文件並 `set -a; source .env; set +a`。

### OpenAI TTS

**已內置** —— 直接看 [`openai.sh`](./openai.sh)。
該文件也是寫 HTTP-based provider 的**官方參考實現**：jq 構造 JSON
payload、curl `-fsS` 提交、可選 base URL（接 Azure-OpenAI / 代理）、
可選 model env var、空音色 fallback 到默認值。新接 REST API 的
provider 直接抄它起手最快。

啓用：

```bash
export OPENAI_API_KEY=sk-...
PRESENTATION_TTS=openai npm run synthesize-audio
# 用 HD 模型 + 別的音色
OPENAI_TTS_MODEL=tts-1-hd npm run synthesize-audio -- --provider=openai --voice=nova
```

### ElevenLabs — `tts-providers/elevenlabs.sh`

```bash
# Docs:   https://elevenlabs.io/docs/api-reference/text-to-speech
# Env:    ELEVENLABS_API_KEY=...
# Voice:  pass voice ID; "Rachel" default is 21m00Tcm4TlvDq8ikWAM
# Model:  eleven_multilingual_v2 supports Chinese; eleven_turbo_v2_5 cheaper

tts_check() {
  command -v curl >/dev/null || { echo "✗ curl not found" >&2; return 1; }
  command -v jq   >/dev/null || { echo "✗ jq not found"   >&2; return 1; }
  [[ -n "${ELEVENLABS_API_KEY:-}" ]] || { echo "✗ ELEVENLABS_API_KEY not set" >&2; return 1; }
}

tts_install_help() {
  cat <<'EOF' >&2
Set your ElevenLabs key first:
  export ELEVENLABS_API_KEY=...       # get one at https://elevenlabs.io
EOF
}

tts_synthesize() {
  local text="$1" out="$2" voice="${3:-21m00Tcm4TlvDq8ikWAM}"
  local payload
  payload=$(jq -n --arg t "$text" \
    '{text:$t, model_id:"eleven_multilingual_v2"}')

  curl -fsS -o "$out" -X POST \
    "https://api.elevenlabs.io/v1/text-to-speech/$voice" \
    -H "xi-api-key: $ELEVENLABS_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$payload"
}
```

### edge-tts — `tts-providers/edge-tts.sh`（免費 / 無 API key）

```bash
# Docs:   https://github.com/rany2/edge-tts
# Install: pip install edge-tts
# Voices: edge-tts --list-voices
#   zh-CN-YunxiNeural     (男聲)
#   zh-CN-XiaoxiaoNeural  (女聲)
#   en-US-AriaNeural      (英文女聲)
#   en-US-GuyNeural       (英文男聲)

tts_check() {
  command -v edge-tts >/dev/null || { echo "✗ edge-tts not found" >&2; return 1; }
}

tts_install_help() {
  cat <<'EOF' >&2
Install edge-tts (free, uses Microsoft Edge's TTS backend, no API key):
  pip install edge-tts
List available voices:
  edge-tts --list-voices | less
EOF
}

tts_synthesize() {
  local text="$1" out="$2" voice="${3:-zh-CN-YunxiNeural}"
  edge-tts --text "$text" --voice "$voice" --write-media "$out" >/dev/null 2>&1
}
```

### macOS `say` — `tts-providers/say.sh`（離線 / 兜底）

```bash
# 系統自帶，零依賴，適合 CI 跑通流程 / 離線預覽。
# 中文音色：Tingting / Sinji / Meijia（看 `say -v ?` 全列表）
# 輸出是 aiff，要 ffmpeg 轉 mp3（Auto 模式 audio 標籤默認認 mp3）。

tts_check() {
  command -v say     >/dev/null || { echo "✗ 'say' not available (macOS only)" >&2; return 1; }
  command -v ffmpeg  >/dev/null || { echo "✗ ffmpeg not found (brew install ffmpeg)" >&2; return 1; }
}

tts_install_help() {
  cat <<'EOF' >&2
macOS-only provider. Needs ffmpeg for aiff→mp3:
  brew install ffmpeg
List voices:  say -v ?
EOF
}

tts_synthesize() {
  local text="$1" out="$2" voice="${3:-Tingting}"
  local tmp
  tmp=$(mktemp -t tts).aiff
  say -v "$voice" -o "$tmp" "$text" \
    && ffmpeg -y -i "$tmp" -codec:a libmp3lame -qscale:a 2 "$out" >/dev/null 2>&1
  local code=$?
  rm -f "$tmp"
  return $code
}
```

### Azure Speech — `tts-providers/azure.sh`

```bash
# Docs:    https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech
# Env:     AZURE_SPEECH_KEY=...   AZURE_SPEECH_REGION=eastus
# SSML payload — Azure requires SSML, not plain JSON

tts_check() {
  command -v curl >/dev/null || { echo "✗ curl not found" >&2; return 1; }
  [[ -n "${AZURE_SPEECH_KEY:-}"    ]] || { echo "✗ AZURE_SPEECH_KEY not set"    >&2; return 1; }
  [[ -n "${AZURE_SPEECH_REGION:-}" ]] || { echo "✗ AZURE_SPEECH_REGION not set" >&2; return 1; }
}

tts_install_help() {
  cat <<'EOF' >&2
Set Azure Speech credentials:
  export AZURE_SPEECH_KEY=...
  export AZURE_SPEECH_REGION=eastus   # or your resource's region
EOF
}

tts_synthesize() {
  local text="$1" out="$2" voice="${3:-zh-CN-YunxiNeural}"
  local lang="${voice%%-*}-${voice#*-}"; lang="${lang%%-*}-${lang#*-}"  # "zh-CN"
  local ssml="<speak version='1.0' xml:lang='$lang'><voice xml:lang='$lang' name='$voice'>$(printf '%s' "$text" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')</voice></speak>"

  curl -fsS -o "$out" -X POST \
    "https://${AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1" \
    -H "Ocp-Apim-Subscription-Key: $AZURE_SPEECH_KEY" \
    -H "Content-Type: application/ssml+xml" \
    -H "X-Microsoft-OutputFormat: audio-24khz-48kbitrate-mono-mp3" \
    -H "User-Agent: web-video-presentation" \
    --data-binary "$ssml"
}
```

### Google Cloud TTS — `tts-providers/gcloud.sh`

```bash
# Docs:   https://cloud.google.com/text-to-speech/docs/reference/rest
# Auth:   easiest is `gcloud auth application-default login`
#         (or set GOOGLE_APPLICATION_CREDENTIALS to a service-account json)
# Voices: zh-CN-Wavenet-A / zh-CN-Neural2-A / en-US-Neural2-J etc.

tts_check() {
  command -v curl   >/dev/null || { echo "✗ curl not found" >&2; return 1; }
  command -v jq     >/dev/null || { echo "✗ jq not found" >&2; return 1; }
  command -v base64 >/dev/null || { echo "✗ base64 not found" >&2; return 1; }
  command -v gcloud >/dev/null || { echo "✗ gcloud not found" >&2; return 1; }
  gcloud auth application-default print-access-token >/dev/null 2>&1 || {
    echo "✗ gcloud is not authenticated (run: gcloud auth application-default login)" >&2
    return 1
  }
}

tts_install_help() {
  cat <<'EOF' >&2
Install gcloud SDK and authenticate:
  https://cloud.google.com/sdk/docs/install
  gcloud auth application-default login
  gcloud services enable texttospeech.googleapis.com
EOF
}

tts_synthesize() {
  local text="$1" out="$2" voice="${3:-zh-CN-Wavenet-A}"
  local lang="${voice%-*}"; lang="${lang%-*}"  # "zh-CN"
  local token
  token=$(gcloud auth application-default print-access-token)

  local payload
  payload=$(jq -n --arg t "$text" --arg v "$voice" --arg l "$lang" \
    '{input:{text:$t}, voice:{languageCode:$l, name:$v}, audioConfig:{audioEncoding:"MP3"}}')

  curl -fsS -X POST https://texttospeech.googleapis.com/v1/text:synthesize \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    | jq -r '.audioContent' | base64 -d > "$out"
}
```

---

## 設計要點（自己寫 provider 時記住）

1. **`set -e` 友好**：runner 用 `set -euo pipefail`，所以你的函數裡要麼明確處理失敗，要麼讓命令自然非零退出。不要吞錯誤。

2. **靜默成功，喧鬧失敗**：成功時不打印任何東西到 stdout（runner 自己打進度條）；失敗時往 stderr 打詳細原因。把 CLI 工具的 stdout 重定向到 `/dev/null`，stderr 留着看。

3. **mp3 輸出**：瀏覽器裏 `<audio>` 標籤最穩喫 mp3。能直接出 mp3 就出 mp3；非 mp3 後端在函數末尾加一步 ffmpeg。

4. **音色 fallback**：`$3` 可能是空字符串。給一個合理的默認值（你最常用的中文音色 / 英文音色），不要因爲沒傳音色就報錯。

5. **不要做並發**：runner 是串行的（避免 rate limit）。provider 函數也別在內部 fork 多線程。

6. **不要修改全局狀態**：provider 文件被 `source` 進 runner 的 shell。別 `cd`、別改 `IFS`、別 `set -e/+e` 切換，否則會污染 runner。把局部變量都 `local`。

   ⚠️ 一個坑：runner 用 `set -u`，**macOS 默認 bash 3.2 在 `"${arr[@]}"` 展開空數組時會炸 `unbound variable`**。如果你的 provider 需要"可選 --voice 參數"，**不要**用 `local args=(); [[ -n $voice ]] && args=(--voice $v); cmd "${args[@]}"` —— 直接寫兩個 if 分支調命令（看 `minimax.sh` 的寫法）。

7. **API 長度上限**：單段大多數 API 都有上限（OpenAI ~4096 chars / MiniMax ~5000 / ElevenLabs ~5000）。Skill 的 narrations 單段一般 < 200 字符，正常不會撞到。如果你的 narration 撞到了，**先回去拆 step**——一個 step 的口播本來就不該這麼長。

---

## 調試

```bash
# 看 runner 怎麼調你的 provider
bash -x scripts/synthesize-audio.sh

# 跑單段試試，不動 audio-segments.json
source scripts/tts-providers/<name>.sh
tts_check && tts_synthesize "測試一下" /tmp/test.mp3 ""
afplay /tmp/test.mp3   # macOS 播一下聽聽
```

跑通了再 `npm run synthesize-audio`。
