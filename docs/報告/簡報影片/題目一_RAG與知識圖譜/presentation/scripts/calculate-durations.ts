import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, "..");
const SEGMENTS_PATH = resolve(ROOT, "audio-segments.json");
const OUT_PATH = resolve(ROOT, "src/app/registry/durations.json");

function getDuration(filePath: string, text: string): number {
  try {
    const cmd = `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${filePath}"`;
    const stdout = execSync(cmd, { stdio: ["pipe", "pipe", "ignore"] })
      .toString()
      .trim();
    const duration = parseFloat(stdout);
    if (!isNaN(duration) && duration > 0) {
      return duration;
    }
  } catch {
    // Fallback if ffprobe is missing or fails
  }
  const textLen = text ? text.length : 0;
  return Math.max(1.5, textLen / 4.2); // ~4.2 chars per second
}

function main() {
  if (!existsSync(SEGMENTS_PATH)) {
    console.error(`✗ audio-segments.json not found. Run extract-narrations first.`);
    process.exit(1);
  }

  const segments = JSON.parse(readFileSync(SEGMENTS_PATH, "utf-8"));
  const durations: Record<string, number> = {};

  for (const seg of segments) {
    const relativeAudioPath = `src/assets/audio/${seg.chapter}/${seg.step}.mp3`;
    const fullAudioPath = resolve(ROOT, relativeAudioPath);

    const duration = existsSync(fullAudioPath)
      ? getDuration(fullAudioPath, seg.text)
      : Math.max(1.5, seg.text.length / 4.2);

    // Register with match path in AudioService
    durations[`/src/assets/audio/${seg.chapter}/${seg.step}.mp3`] = parseFloat(
      duration.toFixed(2),
    );
  }

  writeFileSync(OUT_PATH, JSON.stringify(durations, null, 2) + "\n", "utf-8");
  console.log(`✓ Generated durations cache at ${OUT_PATH}`);
}

main();
