import { spawn } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync, mkdirSync, unlinkSync } from "node:fs";
import { resolve, join } from "node:path";
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import http from "node:http";

const PORT = 5174;
const TARGET_URL = `http://localhost:${PORT}/?auto=1`;

// Check if the Vite dev server is running
function isServerRunning(urlStr: string): Promise<boolean> {
  return new Promise((resolve) => {
    const url = new URL(urlStr);
    const req = http.request(
      {
        method: "HEAD",
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        timeout: 1000,
      },
      (res) => {
        resolve(res.statusCode === 200 || res.statusCode === 404 || res.statusCode === 302);
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.end();
  });
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  console.log(`[Record] 正在檢查 Vite 開發伺服器是否在連接埠 ${PORT} 啟動...`);
  let spawnedServer: any = null;

  const running = await isServerRunning(`http://localhost:${PORT}`);
  if (!running) {
    console.log(`[Record] 偵測到開發伺服器未啟動，正在自動啟動 npm run dev...`);
    spawnedServer = spawn("npm", ["run", "dev"], {
      stdio: "ignore",
      shell: true,
    });

    // Wait up to 60 seconds for the server to boot
    let ok = false;
    for (let i = 0; i < 120; i++) {
      await delay(500);
      if (await isServerRunning(`http://localhost:${PORT}`)) {
        ok = true;
        break;
      }
    }

    if (!ok) {
      console.error(`[Record] 錯誤：無法啟動開發伺服器。請手動執行 npm run dev，然後重新運行此錄影腳本。`);
      if (spawnedServer) spawnedServer.kill();
      process.exit(1);
    }
    console.log(`[Record] 開發伺服器已成功啟動！`);
  } else {
    console.log(`[Record] 開發伺服器已在運行中。`);
  }

  console.log(`[Record] 正在啟動 Playwright 瀏覽器進行自動錄影...`);
  // Try to use locally installed Google Chrome or Microsoft Edge to avoid downloading large binaries
  let browser;
  try {
    browser = await chromium.launch({
      channel: "chrome", // Try Google Chrome first
      headless: true,
    });
  } catch {
    try {
      browser = await chromium.launch({
        channel: "msedge", // Try Edge
        headless: true,
      });
    } catch {
      console.log(`[Record] 未找到本機安裝的 Chrome 或 Edge，正在使用預設 Chromium 啟動...`);
      browser = await chromium.launch({
        headless: true,
      });
    }
  }

  const recordingsDir = resolve("recordings");
  if (!existsSync(recordingsDir)) {
    mkdirSync(recordingsDir, { recursive: true });
  }

  const context = await browser.newContext({
    recordVideo: {
      dir: recordingsDir,
      size: { width: 1920, height: 1080 },
    },
    viewport: { width: 1920, height: 1080 },
  });

  const page = await context.newPage();
  console.log(`[Record] 正在導向簡報頁面: ${TARGET_URL}`);
  await page.goto(TARGET_URL);

  // Clear cursor in localStorage to guarantee we start from the beginning
  await page.evaluate(() => {
    localStorage.setItem("presentation-cursor-v5", JSON.stringify({ chapter: 0, step: 0 }));
  });
  await page.reload();

  // Wait for the "Press SPACE to start" page to settle
  await delay(1000);

  console.log(`[Record] 觸發 Space 啟動自動播放簡報與錄製...`);
  await page.keyboard.press("Space");

  console.log(`[Record] 簡報播放中，正在進行錄影...`);
  // Poll for finish signal
  let finished = false;
  const startTime = Date.now();
  const maxTimeout = 10 * 60 * 1000; // 10 minutes safety timeout

  while (Date.now() - startTime < maxTimeout) {
    finished = await page.evaluate(() => (window as any).presentationFinished === true);
    if (finished) {
      break;
    }
    await delay(500);
  }

  if (finished) {
    console.log(`[Record] 偵測到簡報已播放完畢！等待 2 秒收尾...`);
    await delay(2000);
  } else {
    console.log(`[Record] 警告：達到安全超時時間，強制結束錄製。`);
  }

  // Close browser contexts to finalize the video recording
  await context.close();
  await browser.close();

  if (spawnedServer) {
    console.log(`[Record] 正在關閉自動啟動的開發伺服器...`);
    // Kill the entire process tree on Windows/Linux
    if (process.platform === "win32") {
      try {
        execSync(`taskkill /pid ${spawnedServer.pid} /T /F`, { stdio: "ignore" });
      } catch {
        spawnedServer.kill();
      }
    } else {
      spawnedServer.kill();
    }
  }

  // Find the newly recorded video file
  const videoFiles = readdirSync(recordingsDir)
    .map((file) => join(recordingsDir, file))
    .filter((file) => file.endsWith(".webm"))
    .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);

  if (videoFiles.length === 0) {
    console.error(`[Record] 錯誤：找不到產生的錄影檔案！`);
    process.exit(1);
  }

  // Find the most recent file in recordings directory (which will be Playwright's recording)
  const rawVideoPath = videoFiles[0]!;
  console.log(`[Record] 畫面錄製成功，原始檔存於：${rawVideoPath}`);

  // Now, merge with audio track
  console.log(`[Record] 正在進行音軌合成與轉檔 (MP4)...`);
  await mergeAudioAndVideo(rawVideoPath);
}

async function mergeAudioAndVideo(videoPath: string) {
  const segmentsPath = resolve("audio-segments.json");
  const durationsPath = resolve("src/app/registry/durations.json");
  const tempAudioPath = resolve("recordings/temp_audio.mp3");
  const outputPath = resolve("recordings/presentation.mp4");

  if (!existsSync(segmentsPath)) {
    console.error(`[Record] 錯誤：找不到 audio-segments.json。請先執行 npm run extract-narrations。`);
    process.exit(1);
  }

  const segments = JSON.parse(readFileSync(segmentsPath, "utf-8"));
  let durations: Record<string, number> = {};
  if (existsSync(durationsPath)) {
    durations = JSON.parse(readFileSync(durationsPath, "utf-8"));
  }

  // Construct FFmpeg audio inputs
  const inputs: string[] = [];
  let filterComplex = "";
  let inputIdx = 0;

  for (const seg of segments) {
    const audioFile = `public/audio/${seg.chapter}/${seg.step}.mp3`;
    if (seg.text === "") {
      // 1.5s silence
      inputs.push("-f lavfi -t 1.5 -i anullsrc=r=24000:cl=mono");
      filterComplex += `[${inputIdx}:a]`;
      inputIdx++;
    } else {
      if (existsSync(audioFile)) {
        inputs.push(`-i "${audioFile}"`);
        filterComplex += `[${inputIdx}:a]`;
        inputIdx++;
      } else {
        // fallback silence
        const key = `/src/assets/audio/${seg.chapter}/${seg.step}.mp3`;
        const dur = durations[key] || Math.max(1.5, seg.text.length / 4.2);
        inputs.push(`-f lavfi -t ${dur} -i anullsrc=r=24000:cl=mono`);
        filterComplex += `[${inputIdx}:a]`;
        inputIdx++;
      }
      // 200ms silence padding
      inputs.push("-f lavfi -t 0.2 -i anullsrc=r=24000:cl=mono");
      filterComplex += `[${inputIdx}:a]`;
      inputIdx++;
    }
  }

  // 2s silence padding at the end
  inputs.push("-f lavfi -t 2.0 -i anullsrc=r=24000:cl=mono");
  filterComplex += `[${inputIdx}:a]`;
  inputIdx++;

  filterComplex += `concat=n=${inputIdx}:v=0:a=1[outa]`;

  console.log(`[Record] 正在執行音軌合併...`);
  const audioCmd = `ffmpeg -y ${inputs.join(" ")} -filter_complex "${filterComplex}" -map "[outa]" "${tempAudioPath}"`;
  
  try {
    execSync(audioCmd, { stdio: "ignore" });
    console.log(`[Record] 音軌合併成功，暫存於: ${tempAudioPath}`);
  } catch (err: any) {
    console.error(`[Record] 錯誤：音軌合併失敗:`, err.message);
    process.exit(1);
  }

  console.log(`[Record] 正在合併音視頻並輸出為 MP4...`);
  // Merge video and audio, use libx264 for widest compatibility
  const mergeCmd = `ffmpeg -y -i "${videoPath}" -i "${tempAudioPath}" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "${outputPath}"`;

  try {
    execSync(mergeCmd, { stdio: "ignore" });
    console.log(`[Record] 錄影轉換成功！成品已儲存至: ${outputPath}`);

    // Clean up temporary files with a short delay to release OS handles
    await delay(1000);
    try {
      if (existsSync(tempAudioPath)) unlinkSync(tempAudioPath);
      if (existsSync(videoPath)) unlinkSync(videoPath);
    } catch (e) {
      console.warn(`[Record] 清理暫存檔時發生警告 (可能檔案被鎖定):`, (e as any).message);
    }
  } catch (err: any) {
    console.error(`[Record] 錯誤：音視頻合併失敗:`, err.message);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(`[Record] 錄影過程出錯:`, err);
  process.exit(1);
});
