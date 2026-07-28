import { Component, inject, computed, signal, HostListener } from "@angular/core";
import { CommonModule } from "@angular/common";
import { StepperService } from "./services/stepper.service";
import { AudioService } from "./services/audio.service";
import { EditorService } from "./services/editor.service";
import { SyncService } from "./services/sync.service";
import { StageComponent } from "./components/stage/stage.component";
import { ProgressBarComponent } from "./components/progress-bar/progress-bar.component";
import { TextFormatToolbarComponent } from "./components/text-format-toolbar/text-format-toolbar.component";
import { PresenterConsoleComponent } from "./components/presenter-console/presenter-console.component";

@Component({
  selector: "app-root",
  standalone: true,
  imports: [
    CommonModule,
    StageComponent,
    ProgressBarComponent,
    TextFormatToolbarComponent,
    PresenterConsoleComponent,
  ],
  templateUrl: "./app.component.html",
  styleUrls: ["./app.component.css"],
})
export class AppComponent {
  readonly stepper = inject(StepperService);
  readonly audio = inject(AudioService);
  readonly editor = inject(EditorService);
  readonly sync = inject(SyncService);

  readonly topNavVisible = signal<boolean>(false);
  private leaveTimer: any = null;
  private mouseMoveTimer: any = null;
  private isMouseOverNav = false;

  @HostListener("window:mousemove", ["$event"])
  onMouseMoveGlobal(e: MouseEvent) {
    // 只有在放映模式（非編輯模式）下才啟用滑鼠靜止自動隱藏
    if (this.editor.isEditing()) return;

    // 只要滑鼠移動，就立刻顯示控制列
    this.topNavVisible.set(true);

    // 重設靜止計時器
    if (this.mouseMoveTimer) {
      clearTimeout(this.mouseMoveTimer);
    }

    // 2秒後如果滑鼠沒有繼續移動，且滑鼠不在控制列上方，就自動隱藏
    this.mouseMoveTimer = setTimeout(() => {
      if (!this.isMouseOverNav && !this.editor.isEditing()) {
        this.topNavVisible.set(false);
      }
    }, 2000);
  }

  onNavMouseEnter() {
    this.isMouseOverNav = true;
    if (this.leaveTimer) {
      clearTimeout(this.leaveTimer);
      this.leaveTimer = null;
    }
    if (this.mouseMoveTimer) {
      clearTimeout(this.mouseMoveTimer);
      this.mouseMoveTimer = null;
    }
    this.topNavVisible.set(true);
  }

  onNavMouseLeave() {
    this.isMouseOverNav = false;
    if (this.leaveTimer) {
      clearTimeout(this.leaveTimer);
    }
    this.leaveTimer = setTimeout(() => {
      if (!this.editor.isEditing()) {
        this.topNavVisible.set(false);
      }
    }, 2000);
  }

  readonly playbackModeText = computed(() => {
    const m = this.audio.mode();
    if (m === "auto") return "自動播放";
    if (m === "audio") return "音訊引導";
    return "手動模式";
  });

  onNarrationInput(e: Event) {
    const val = (e.target as HTMLTextAreaElement).value;
    this.editor.updateNarration(this.stepper.currentStep(), val);
  }

  onNoteInput(e: Event) {
    const val = (e.target as HTMLTextAreaElement).value;
    this.editor.updateNote(this.stepper.currentStep(), val);
  }

  toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch((err) => {
        console.warn("進入全螢幕失敗:", err);
      });
    } else {
      document.exitFullscreen().catch((err) => {
        console.warn("退出全螢幕失敗:", err);
      });
    }
  }

  toggleEditMode() {
    this.editor.toggleEditing();
    // 只要切換回放映模式，就自動設定成手動模式
    if (!this.editor.isEditing()) {
      this.audio.mode.set("manual");
    }
  }

  openPresenterMode() {
    if (typeof window !== "undefined") {
      const url = window.location.origin + window.location.pathname + "?presenter=1";
      window.open(url, "_blank");
    }
  }
}
