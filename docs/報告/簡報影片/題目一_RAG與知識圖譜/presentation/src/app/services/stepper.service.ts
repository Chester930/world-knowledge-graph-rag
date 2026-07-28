import { Injectable, signal, computed, effect } from "@angular/core";
import { CHAPTERS } from "../registry/chapters";
import { ChapterDef } from "../registry/types";

export type Cursor = { chapter: number; step: number };
const STORAGE_KEY = "presentation-cursor-v7";

const clamp = (n: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, n));

function sanitize(cursor: Cursor, chapters: ChapterDef[]): Cursor {
  if (chapters.length === 0) return { chapter: 0, step: 0 };
  const chapter = clamp(cursor.chapter | 0, 0, chapters.length - 1);
  const stepCount = chapters[chapter]!.narrations.length;
  const step = clamp(cursor.step | 0, 0, Math.max(0, stepCount - 1));
  return { chapter, step };
}

@Injectable({
  providedIn: "root",
})
export class StepperService {
  readonly chapters = CHAPTERS;

  // Writable Signals
  readonly cursor = signal<Cursor>(this.loadCursor());

  // Computed Signals
  readonly currentChapterIdx = computed(() => this.cursor().chapter);
  readonly currentStep = computed(() => this.cursor().step);
  readonly currentChapter = computed(() => this.chapters[this.currentChapterIdx()]);
  readonly totalChapters = computed(() => this.chapters.length);
  readonly chapterTotalSteps = computed(() => this.currentChapter()?.narrations.length ?? 0);

  readonly offsets = computed(() => {
    const arr: number[] = [];
    let acc = 0;
    for (const c of this.chapters) {
      arr.push(acc);
      acc += c.narrations.length;
    }
    return arr;
  });

  readonly totalGlobal = computed(() =>
    this.chapters.reduce((sum, c) => sum + c.narrations.length, 0),
  );

  readonly globalIndex = computed(() =>
    (this.offsets()[this.currentChapterIdx()] ?? 0) + this.currentStep(),
  );

  constructor() {
    // Sync cursor changes to localStorage
    effect(() => {
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(this.cursor()));
      } catch {
        /* ignore */
      }
    });

    // Global keyboard listener
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

        if (e.key === "ArrowRight" || e.key === " ") {
          e.preventDefault();
          const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : null;
          const isAutoOrAudio = q && (q.get("auto") === "1" || q.get("audio") === "1");
          if (e.key === " " && isAutoOrAudio) {
            return;
          }
          this.next();
        } else if (e.key === "ArrowLeft" || e.key === "Backspace") {
          e.preventDefault();
          this.prev();
        } else if (e.key === "Home") {
          this.jumpToChapter(0, 0);
        } else if (e.key === "End") {
          const last = this.chapters.length - 1;
          this.jumpToChapter(last, this.chapters[last]!.narrations.length - 1);
        } else if (e.key >= "1" && e.key <= "9") {
          const n = Number(e.key) - 1;
          if (n < this.chapters.length) this.jumpToChapter(n, 0);
        }
      });
    }
  }

  private loadCursor(): Cursor {
    const fallback = { chapter: 0, step: 0 };
    if (typeof window === "undefined") return fallback;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) return sanitize(JSON.parse(raw), this.chapters);
    } catch {
      /* ignore */
    }
    return fallback;
  }

  next() {
    const cur = this.cursor();
    const c = this.chapters[cur.chapter];
    if (!c) return;
    if (cur.step < c.narrations.length - 1) {
      this.cursor.set({ ...cur, step: cur.step + 1 });
    } else if (cur.chapter < this.chapters.length - 1) {
      this.cursor.set({ chapter: cur.chapter + 1, step: 0 });
    }
  }

  prev() {
    const cur = this.cursor();
    if (cur.step > 0) {
      this.cursor.set({ ...cur, step: cur.step - 1 });
    } else if (cur.chapter > 0) {
      const p = this.chapters[cur.chapter - 1]!;
      this.cursor.set({ chapter: cur.chapter - 1, step: p.narrations.length - 1 });
    }
  }

  jumpToChapter(idx: number, step = 0) {
    const ch = clamp(idx, 0, this.chapters.length - 1);
    const c = this.chapters[ch]!;
    this.cursor.set({
      chapter: ch,
      step: clamp(step, 0, c.narrations.length - 1),
    });
  }

  jumpToGlobal(g: number) {
    const target = clamp(g, 0, this.totalGlobal() - 1);
    let acc = 0;
    for (let i = 0; i < this.chapters.length; i++) {
      const t = this.chapters[i]!.narrations.length;
      if (target < acc + t) {
        this.cursor.set({ chapter: i, step: target - acc });
        return;
      }
      acc += t;
    }
  }
}
