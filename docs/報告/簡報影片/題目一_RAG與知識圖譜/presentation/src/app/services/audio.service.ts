import { Injectable, signal, computed, effect, inject } from "@angular/core";
import { StepperService } from "./stepper.service";
import durations from "../registry/durations.json";

export type PlaybackMode = "manual" | "audio" | "auto";
const MODE_ORDER: PlaybackMode[] = ["manual", "audio", "auto"];

function readModeFromURL(): PlaybackMode {
  if (typeof window === "undefined") return "manual";
  const q = new URLSearchParams(window.location.search);
  if (q.get("auto") === "1") return "auto";
  if (q.get("audio") === "1") return "audio";
  return "manual";
}

@Injectable({
  providedIn: "root",
})
export class AudioService {
  private readonly stepper = inject(StepperService);

  // Writable Signals
  readonly mode = signal<PlaybackMode>(readModeFromURL());
  readonly autoStarted = signal<boolean>(false);

  private audioRef: HTMLAudioElement | null = null;
  private timer: number | null = null;

  constructor() {
    // Keep URL in sync with mode
    effect(() => {
      const m = this.mode();
      if (typeof window === "undefined") return;
      const url = new URL(window.location.href);
      url.searchParams.delete("audio");
      url.searchParams.delete("auto");
      if (m === "audio") url.searchParams.set("audio", "1");
      if (m === "auto") {
        url.searchParams.set("auto", "1");
        this.autoStarted.set(true);
        (window as any).presentationFinished = false;
        // 當點擊自動播放時，自動變成全螢幕
        if (!document.fullscreenElement) {
          document.documentElement.requestFullscreen().catch((err) => {
            console.warn("自動進入全螢幕失敗（瀏覽器安全性限制，需由使用者點擊事件觸發）：", err);
          });
        }
      } else {
        this.autoStarted.set(false);
      }
      window.history.replaceState(null, "", url.toString());
    }, { allowSignalWrites: true });

    // Reactive audio player effect
    effect(() => {
      const chapter = this.stepper.currentChapter();
      const step = this.stepper.currentStep();
      const m = this.mode();
      const started = this.autoStarted();

      this.stopCurrentAudio();

      if (m === "manual") return;
      if (m === "auto" && !started) return;
      if (!chapter) return;

      const chapterId = chapter.id;
      const audioUrl = `/audio/${chapterId}/${step + 1}.mp3`;
      const narrationText = chapter.narrations[step] || "";

      this.playStepAudio(audioUrl, narrationText);
    });

    // Keyboard listener for M and Space
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", (e: KeyboardEvent) => {
        const target = e.target as HTMLElement;
        if (
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable
        ) {
          return;
        }

        if (e.key === "m" || e.key === "M") {
          e.preventDefault();
          this.cycleMode();
        } else if (e.key === " " && this.mode() === "auto" && !this.autoStarted()) {
          e.preventDefault();
          this.autoStarted.set(true);
          (window as any).presentationFinished = false;
        }
      });
    }

    // Autoplay Policy 解鎖器：一旦使用者點擊網頁或按鍵，自動嘗試重播當前音訊
    if (typeof document !== "undefined") {
      const resumeAudio = () => {
        document.removeEventListener("click", resumeAudio);
        document.removeEventListener("keydown", resumeAudio);
        
        const m = this.mode();
        if (m !== "manual") {
          const chapter = this.stepper.currentChapter();
          const step = this.stepper.currentStep();
          if (chapter) {
            const chapterId = chapter.id;
            const audioUrl = `/audio/${chapterId}/${step + 1}.mp3`;
            const narrationText = chapter.narrations[step] || "";
            // 只有在當前沒有音訊正在播放時，才重新嘗試播放
            if (!this.audioRef || this.audioRef.paused) {
              this.stopCurrentAudio();
              this.playStepAudio(audioUrl, narrationText);
            }
          }
        }
      };
      document.addEventListener("click", resumeAudio);
      document.addEventListener("keydown", resumeAudio);
    }
  }

  cycleMode() {
    const curIdx = MODE_ORDER.indexOf(this.mode());
    const nextIdx = (curIdx + 1) % MODE_ORDER.length;
    this.mode.set(MODE_ORDER[nextIdx]!);
  }

  private stopCurrentAudio() {
    if (this.timer != null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.audioRef) {
      this.audioRef.pause();
      this.audioRef.removeAttribute("src");
      this.audioRef.load();
      this.audioRef = null;
    }
  }

  private playStepAudio(url: string, text: string) {
    let advanced = false;
    const textLen = text ? text.length : 0;
    
    // Get precise duration from durations.json if available
    const urlParts = url.split("/");
    const keySuffix = urlParts.slice(-2).join("/"); // e.g. behavioral-cloning/1.mp3
    let cachedSec: number | undefined;
    for (const key of Object.keys(durations)) {
      if (key.endsWith(keySuffix)) {
        cachedSec = (durations as Record<string, number>)[key];
        break;
      }
    }
    const fallbackMs = cachedSec
      ? cachedSec * 1000
      : Math.min(10000, Math.max(2000, textLen * 250 + 1000));

    const isLastChapter = this.stepper.currentChapterIdx() === this.stepper.totalChapters() - 1;
    const isLastStep = this.stepper.currentStep() === this.stepper.chapterTotalSteps() - 1;
    const isLast = isLastChapter && isLastStep;

    const advanceAfter = (ms: number) => {
      if (this.mode() !== "auto" || advanced) return;
      this.timer = window.setTimeout(() => {
        if (advanced) return;
        advanced = true;
        if (isLast) {
          (window as any).presentationFinished = true;
        } else {
          this.stepper.next();
        }
      }, ms);
    };

    if (textLen > 0) {
      const audio = new Audio(url);
      this.audioRef = audio;
      audio.preload = "auto";

      audio.addEventListener("ended", () => {
        advanceAfter(200); // 200ms trailing silence padding
      });

      audio.addEventListener("error", () => {
        // Fallback if MP3 is missing
        if (this.mode() === "auto") {
          advanceAfter(fallbackMs);
        }
      });

      audio.play().catch((err) => {
        console.warn("Autoplay blocked or audio missing, using fallback timer:", err);
        if (this.mode() === "auto") {
          advanceAfter(fallbackMs);
        }
      });
    } else if (this.mode() === "auto") {
      // Empty step text (silent transition)
      advanceAfter(1500);
    }
  }
}
