import { Injectable, signal, computed, effect, inject } from "@angular/core";
import { StepperService } from "./stepper.service";

@Injectable({
  providedIn: "root",
})
export class EditorService {
  private readonly stepper = inject(StepperService);

  readonly isEditing = signal<boolean>(false);
  readonly editedNarrations = signal<string[]>([]);
  readonly layoutData = signal<any>({});

  // 進入編輯前的快照備份，用以實作「取消/未存檔還原」
  private narrationsSnapshot: string[] = [];
  private layoutSnapshot: any = null;

  // Get current step notes
  readonly currentNote = computed(() => {
    const step = this.stepper.currentStep();
    const layout = this.layoutData();
    if (layout?.notes && Array.isArray(layout.notes)) {
      return layout.notes[step] || "";
    }
    return "";
  });

  // Get current step narration
  readonly currentNarration = computed(() => {
    const step = this.stepper.currentStep();
    return this.editedNarrations()[step] || "";
  });

  constructor() {
    // Automatically initialize/copy chapter data when chapter changes
    effect(
      () => {
        const chapter = this.stepper.currentChapter();
        if (!chapter) return;

        // Copy narrations
        this.editedNarrations.set([...chapter.narrations]);

        // Copy layout.json, ensure notes and steps structure exists
        const layoutCopy = JSON.parse(JSON.stringify(chapter.layout || {}));
        if (!layoutCopy.notes) {
          layoutCopy.notes = Array(chapter.narrations.length).fill("");
        }
        if (!layoutCopy.steps) {
          layoutCopy.steps = {};
        }
        this.layoutData.set(layoutCopy);
      },
      { allowSignalWrites: true },
    );
  }

  updateNarration(step: number, text: string) {
    this.editedNarrations.update((arr) => {
      const copy = [...arr];
      copy[step] = text;
      return copy;
    });
  }

  updateNote(step: number, text: string) {
    this.layoutData.update((layout) => {
      const copy = { ...layout };
      if (!copy.notes) {
        copy.notes = Array(this.stepper.chapterTotalSteps()).fill("");
      }
      copy.notes[step] = text;
      return copy;
    });
  }

  // Getters with fallback defaults
  getBlockX(step: number, blockId: string, defaultVal: number): number {
    return this.layoutData().steps?.[`step${step}`]?.[blockId]?.x ?? defaultVal;
  }

  getBlockY(step: number, blockId: string, defaultVal: number): number {
    return this.layoutData().steps?.[`step${step}`]?.[blockId]?.y ?? defaultVal;
  }

  getBlockW(step: number, blockId: string, defaultVal: number): number {
    return this.layoutData().steps?.[`step${step}`]?.[blockId]?.w ?? defaultVal;
  }

  getBlockH(step: number, blockId: string, defaultVal: number): number {
    return this.layoutData().steps?.[`step${step}`]?.[blockId]?.h ?? defaultVal;
  }

  getBlockText(step: number, blockId: string, defaultVal: string): string {
    return this.layoutData().steps?.[`step${step}`]?.[blockId]?.text ?? defaultVal;
  }

  updateBlockLayout(
    step: number,
    blockId: string,
    rect: { x?: number; y?: number; w?: number; h?: number; text?: string },
  ) {
    this.layoutData.update((layout) => {
      const copy = { ...layout };
      if (!copy.steps) copy.steps = {};
      const stepKey = `step${step}`;
      if (!copy.steps[stepKey]) copy.steps[stepKey] = {};
      if (!copy.steps[stepKey][blockId]) {
        copy.steps[stepKey][blockId] = { x: 0, y: 0, w: 100, h: 100, text: "" };
      }

      const block = copy.steps[stepKey][blockId];
      if (rect.x !== undefined) block.x = rect.x;
      if (rect.y !== undefined) block.y = rect.y;
      if (rect.w !== undefined) block.w = rect.w;
      if (rect.h !== undefined) block.h = rect.h;
      if (rect.text !== undefined) block.text = rect.text;

      return copy;
    });
  }

  toggleEditing() {
    this.isEditing.update((v) => {
      const next = !v;
      if (next) {
        // 進入編輯模式：建立當前狀態備份快照
        this.narrationsSnapshot = JSON.parse(JSON.stringify(this.editedNarrations()));
        this.layoutSnapshot = JSON.parse(JSON.stringify(this.layoutData()));
      } else {
        // 退出編輯模式：如果未按儲存（或者點選放映模式），將狀態還原為上次儲存的快照
        this.editedNarrations.set(JSON.parse(JSON.stringify(this.narrationsSnapshot)));
        this.layoutData.set(JSON.parse(JSON.stringify(this.layoutSnapshot)));
      }
      return next;
    });
  }

  async save() {
    const chapterId = this.stepper.currentChapter()?.id;
    if (!chapterId) return;

    const payload = {
      chapterId,
      narrations: this.editedNarrations(),
      layout: this.layoutData(),
    };

    try {
      const res = await fetch("/api/save-chapter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        // 儲存成功：將當前新狀態更新至快照，避免退出時被還原
        this.narrationsSnapshot = JSON.parse(JSON.stringify(this.editedNarrations()));
        this.layoutSnapshot = JSON.parse(JSON.stringify(this.layoutData()));
        alert("儲存成功！本地 `narrations.ts` 與 `layout.json` 已更新。");
      } else {
        const errData = await res.json();
        alert(`儲存失敗: ${errData.error || "未知錯誤"}`);
      }
    } catch (err: any) {
      console.error(err);
      alert(`儲存失敗: ${err.message || "網路錯誤"}`);
    }
  }
}
