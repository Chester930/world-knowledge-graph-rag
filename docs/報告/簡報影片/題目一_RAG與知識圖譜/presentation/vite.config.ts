import { defineConfig } from "vite";
import angular from "@analogjs/vite-plugin-angular";
import { join } from "node:path";
import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { execSync } from "node:child_process";

// 取得 MP3 精確長度或 fallback 計算
function calculateMp3Duration(filePath: string, text: string): number {
  if (existsSync(filePath)) {
    try {
      const cmd = `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${filePath}"`;
      const stdout = execSync(cmd, { stdio: ["pipe", "pipe", "ignore"] }).toString().trim();
      const dur = parseFloat(stdout);
      if (!isNaN(dur) && dur > 0) return dur;
    } catch {
      // ffprobe 失敗或未安裝時使用 fallback
    }
  }
  return Math.max(1.5, (text || "").length / 4.2); // 估算 1 秒約 4.2 個字
}

// 增量語音合成邏輯
function syncTtsForChanges(chapterId: string, oldNarrations: string[], newNarrations: string[]) {
  const publicAudioDir = join(process.cwd(), "public", "audio", chapterId);
  const durationsPath = join(process.cwd(), "src", "app", "registry", "durations.json");
  
  if (!existsSync(publicAudioDir)) {
    mkdirSync(publicAudioDir, { recursive: true });
  }

  // 載入當前 durations 快取
  let durations: Record<string, number> = {};
  if (existsSync(durationsPath)) {
    try {
      durations = JSON.parse(readFileSync(durationsPath, "utf-8"));
    } catch {
      durations = {};
    }
  }

  // 比對每一頁的口播，若有改變就重新生成
  const maxLength = Math.max(oldNarrations.length, newNarrations.length);
  let hasChanged = false;

  for (let i = 0; i < maxLength; i++) {
    const oldText = oldNarrations[i] || "";
    const newText = newNarrations[i] || "";
    const stepNum = i + 1;
    const audioFileName = `${stepNum}.mp3`;
    const outPath = join(publicAudioDir, audioFileName);
    const durationKey = `/audio/${chapterId}/${audioFileName}`;

    // 如果台詞被刪除了，清除對應語音
    if (i >= newNarrations.length) {
      delete durations[durationKey];
      hasChanged = true;
      continue;
    }

    // 當文字有變更，或者 MP3 實體檔案遺失時，觸發重新合成
    if (oldText !== newText || !existsSync(outPath)) {
      console.log(`[TTS] 檢測到 Step ${stepNum} 口播台詞有變更，重新合成語音中...`);
      try {
        // 呼叫 edge-tts (使用台灣中文女聲 HsiaoChen)
        const escapedText = newText.replace(/"/g, '\\"').replace(/\n/g, " ");
        const ttsCmd = `edge-tts --voice "zh-TW-HsiaoChenNeural" --text "${escapedText}" --write-media "${outPath}"`;
        execSync(ttsCmd, { env: { ...process.env, PATH: process.env.PATH + ";C:\\Users\\666\\AppData\\Roaming\\Python\\Python313\\Scripts" } });
        
        // 重新計算新 MP3 的播放時長並更新
        const newDur = calculateMp3Duration(outPath, newText);
        durations[durationKey] = parseFloat(newDur.toFixed(2));
        hasChanged = true;
        console.log(`[TTS] Step ${stepNum} 語音合成成功，時長: ${newDur.toFixed(2)} 秒`);
      } catch (err: any) {
        console.error(`[TTS] Step ${stepNum} 語音合成失敗:`, err.message);
      }
    }
  }

  // 儲存更新後的 durations
  if (hasChanged) {
    writeFileSync(durationsPath, JSON.stringify(durations, null, 2) + "\n", "utf-8");
  }
}

export default defineConfig({
  plugins: [
    angular(),
    {
      name: "save-presentation-data",
      configureServer(server) {
        server.middlewares.use((req: any, res: any, next: any) => {
          if (req.method === "POST" && req.url === "/api/save-chapter") {
            let body = "";
            req.on("data", (chunk: any) => {
              body += chunk;
            });
            req.on("end", () => {
              try {
                const data = JSON.parse(body);
                const { chapterId, narrations, layout } = data;

                if (!chapterId || !narrations || !layout) {
                  res.statusCode = 400;
                  res.end(JSON.stringify({ error: "Missing required fields" }));
                  return;
                }

                // Resolve target files inside the chapter directory
                const chapterDir = join(process.cwd(), "src", "app", "chapters", chapterId);
                const narrationsFile = join(chapterDir, "narrations.ts");

                // 讀取當前的舊口播，用作增量比對
                let oldNarrations: string[] = [];
                if (existsSync(narrationsFile)) {
                  const content = readFileSync(narrationsFile, "utf-8");
                  const match = content.match(/export const narrations: string\[\] = (\[[\s\S]*?\]);/);
                  if (match && match[1]) {
                    try {
                      // 移除 trailing comma 以便 JSON.parse 解析
                      const jsonText = match[1].replace(/,(\s*\])/, "$1");
                      oldNarrations = JSON.parse(jsonText);
                    } catch (e) {
                      // 解析失敗時，使用簡單文字切割作為 fallback
                      console.warn("無法精確解析舊 narrations.ts，改用後備匹配");
                    }
                  }
                }
                
                // 執行增量語音同步
                syncTtsForChanges(chapterId, oldNarrations, narrations);

                // Write narrations.ts
                const narrationsContent = `export const narrations: string[] = ${JSON.stringify(narrations, null, 2)};\n`;
                writeFileSync(narrationsFile, narrationsContent, "utf-8");

                // Write layout.json
                writeFileSync(join(chapterDir, "layout.json"), JSON.stringify(layout, null, 2) + "\n", "utf-8");

                res.statusCode = 200;
                res.setHeader("Content-Type", "application/json");
                res.end(JSON.stringify({ success: true }));
              } catch (err: any) {
                res.statusCode = 500;
                res.end(JSON.stringify({ error: err.message || "Failed to save" }));
              }
            });
          } else {
            next();
          }
        });
      },
    },
  ],
  resolve: {
    mainFields: ["module", "main", "es2015"],
  },
  server: {
    port: 5174,
    fs: { allow: [".."] },
  },
});
