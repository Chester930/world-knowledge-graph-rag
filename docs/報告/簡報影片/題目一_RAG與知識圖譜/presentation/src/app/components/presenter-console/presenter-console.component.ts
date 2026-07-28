import { Component, OnInit, OnDestroy, inject, signal, computed } from "@angular/core";
import { CommonModule } from "@angular/common";
import { StepperService } from "../../services/stepper.service";
import { EditorService } from "../../services/editor.service";
import { SyncService } from "../../services/sync.service";
import { StageComponent } from "../stage/stage.component";

@Component({
  selector: "app-presenter-console",
  standalone: true,
  imports: [CommonModule, StageComponent],
  template: `
    <div class="console-wrapper" data-no-advance>
      <!-- 頂部計時器與標題 -->
      <div class="console-header">
        <div class="brand">
          <span class="pulse-dot"></span>
          <span>PRESENTER CONSOLE</span>
        </div>
        
        <!-- 計時器 -->
        <div class="timer-box">
          <span class="timer-label">演講時間</span>
          <span class="timer-num">{{ timeString() }}</span>
          <div class="timer-controls">
            <button class="timer-btn" (click)="toggleTimer()">
              {{ timerRunning() ? '⏸' : '▶' }}
            </button>
            <button class="timer-btn" (click)="resetTimer()">🔄</button>
          </div>
        </div>
      </div>

      <!-- 口播備忘錄區 -->
      <div class="console-section note-section">
        <div class="section-title">
          <span class="dot red-dot"></span>
          <span>當前口播備註 (Step {{ stepper.currentStep() + 1 }})</span>
        </div>
        <div class="notes-content">
          <p class="current-note-text" *ngIf="currentNote(); else noNote">
            {{ currentNote() }}
          </p>
          <ng-template #noNote>
            <p class="no-note-text">本步驟無講者備註。請自由發揮！</p>
          </ng-template>
        </div>
      </div>

      <!-- 下一個步驟提示區 -->
      <div class="console-section next-section">
        <div class="section-title">
          <span class="dot green-dot"></span>
          <span>下一步預覽</span>
        </div>
        <div class="next-preview-box">
          <div class="mini-stage-wrapper" *ngIf="hasNextStep(); else noNext">
            <app-stage>
              <ng-container *ngComponentOutlet="nextChapterComponent(); inputs: { step: nextStepIndex() }"></ng-container>
            </app-stage>
          </div>
          <ng-template #noNext>
            <p class="no-next-text">已是最後一個步驟。</p>
          </ng-template>
        </div>
      </div>

      <!-- 快速控制按鈕 -->
      <div class="console-footer">
        <button class="console-ctrl-btn" (click)="stepper.prev()" [disabled]="stepper.cursor().step === 0 && stepper.cursor().chapter === 0">
          ◀ 上一步
        </button>
        <div class="step-indicator">
          <strong>{{ stepper.currentStep() + 1 }}</strong> / {{ stepper.chapterTotalSteps() }}
        </div>
        <button class="console-ctrl-btn ctrl-next" (click)="stepper.next()">
          下一步 ▶
        </button>
      </div>
    </div>
  `,
  styles: [
    `
      .console-wrapper {
        width: 100%;
        height: 100%;
        background: #080c08;
        border-left: 1px solid rgba(0, 255, 136, 0.2);
        display: flex;
        flex-direction: column;
        padding: 24px;
        color: #d3f0d3;
        box-sizing: border-box;
      }

      .console-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        padding-bottom: 16px;
        margin-bottom: 20px;
      }

      .brand {
        display: flex;
        align-items: center;
        gap: 8px;
        font-family: monospace;
        font-size: 0.85rem;
        letter-spacing: 2px;
        color: var(--accent, #00ff88);
      }

      .pulse-dot {
        width: 8px;
        height: 8px;
        background-color: var(--accent, #00ff88);
        border-radius: 50%;
        box-shadow: 0 0 8px var(--accent, #00ff88);
      }

      /* Timer */
      .timer-box {
        display: flex;
        align-items: center;
        gap: 12px;
        background: rgba(0, 0, 0, 0.4);
        padding: 6px 12px;
        border-radius: 8px;
        border: 1px solid rgba(255, 255, 255, 0.05);
      }

      .timer-label {
        font-size: 0.75rem;
        color: rgba(211, 240, 211, 0.5);
      }

      .timer-num {
        font-family: monospace;
        font-size: 1.15rem;
        font-weight: bold;
        color: #fff;
        min-width: 70px;
      }

      .timer-controls {
        display: flex;
        gap: 4px;
      }

      .timer-btn {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #fff;
        width: 24px;
        height: 24px;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.7rem;
        cursor: pointer;
      }

      .timer-btn:hover {
        background: rgba(0, 255, 136, 0.15);
        color: var(--accent, #00ff88);
      }

      /* Console Section */
      .console-section {
        flex: 1;
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 10px;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-bottom: 16px;
        min-height: 0; /* 允許 flex 子項收縮 */
      }

      .note-section {
        flex: 2; /* 備忘錄區佔用較大空間 */
      }

      .section-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.85rem;
        font-weight: bold;
        color: #fff;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
      }

      .red-dot { background-color: #ff3355; box-shadow: 0 0 6px #ff3355; }
      .green-dot { background-color: var(--accent, #00ff88); box-shadow: 0 0 6px var(--accent, #00ff88); }

      .notes-content {
        flex: 1;
        overflow-y: auto;
        padding-right: 4px;
      }

      .current-note-text {
        margin: 0;
        font-size: 1.45rem; /* 大字級備忘錄 */
        line-height: 1.6;
        color: #fff;
        white-space: pre-wrap;
      }

      .no-note-text, .no-next-text {
        margin: 0;
        font-size: 1.05rem;
        color: rgba(211, 240, 211, 0.4);
        font-style: italic;
      }

      .next-preview-box {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        min-height: 0;
        width: 100%;
        margin-top: 4px;
      }

      .mini-stage-wrapper {
        position: relative;
        width: 100%;
        height: 100%;
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid rgba(0, 255, 136, 0.15);
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
        pointer-events: none; /* 穿透，防止觸發任何滑鼠事件 */
      }

      /* Controls Footer */
      .console-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        padding-top: 16px;
        margin-top: auto;
      }

      .console-ctrl-btn {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #d3f0d3;
        padding: 10px 18px;
        border-radius: 8px;
        font-size: 0.9rem;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
      }

      .console-ctrl-btn:hover:not(:disabled) {
        background: rgba(255, 255, 255, 0.1);
        color: #fff;
      }

      .console-ctrl-btn:disabled {
        opacity: 0.3;
        cursor: not-allowed;
      }

      .ctrl-next {
        background: rgba(0, 255, 136, 0.12);
        border-color: rgba(0, 255, 136, 0.25);
        color: var(--accent, #00ff88);
        font-weight: 600;
      }

      .ctrl-next:hover:not(:disabled) {
        background: var(--accent, #00ff88);
        color: #000;
      }

      .step-indicator {
        font-size: 0.85rem;
        color: rgba(211, 240, 211, 0.6);
      }
    `,
  ],
})
export class PresenterConsoleComponent implements OnInit, OnDestroy {
  readonly stepper = inject(StepperService);
  readonly editor = inject(EditorService);
  readonly sync = inject(SyncService);

  readonly timerRunning = signal<boolean>(false);
  private seconds = signal<number>(0);
  private timerInterval: any = null;

  // 當前 Step 講者備註
  readonly currentNote = computed(() => {
    const step = this.stepper.currentStep();
    const notes = this.stepper.currentChapter()?.layout?.notes;
    if (notes && Array.isArray(notes)) {
      return notes[step] || "";
    }
    return "";
  });

  // 下一步的 Chapter 索引和 Step 索引
  readonly nextCursor = computed(() => {
    const cur = this.stepper.cursor();
    const cIdx = cur.chapter;
    const sIdx = cur.step;
    const currentCh = this.stepper.chapters[cIdx];
    if (!currentCh) return null;

    if (sIdx < currentCh.narrations.length - 1) {
      return { chapter: cIdx, step: sIdx + 1 };
    } else if (cIdx < this.stepper.chapters.length - 1) {
      return { chapter: cIdx + 1, step: 0 };
    }
    return null;
  });

  readonly hasNextStep = computed(() => this.nextCursor() !== null);

  readonly nextChapterComponent = computed(() => {
    const next = this.nextCursor();
    if (!next) return null;
    return this.stepper.chapters[next.chapter]?.component ?? null;
  });

  readonly nextStepIndex = computed(() => {
    const next = this.nextCursor();
    return next ? next.step : 0;
  });

  readonly timeString = computed(() => {
    const totalSecs = this.seconds();
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  });

  ngOnInit() {
    this.startTimer();
  }

  ngOnDestroy() {
    this.stopTimer();
  }

  startTimer() {
    this.timerRunning.set(true);
    this.timerInterval = setInterval(() => {
      this.seconds.update((s) => s + 1);
    }, 1000);
  }

  stopTimer() {
    this.timerRunning.set(false);
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
  }

  toggleTimer() {
    if (this.timerRunning()) {
      this.stopTimer();
    } else {
      this.startTimer();
    }
  }

  resetTimer() {
    this.stopTimer();
    this.seconds.set(0);
    this.startTimer();
  }
}
