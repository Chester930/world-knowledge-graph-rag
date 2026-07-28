import { Component, OnInit, OnDestroy, signal, inject, ElementRef } from "@angular/core";
import { CommonModule } from "@angular/common";
import { StepperService } from "../../services/stepper.service";
import { EditorService } from "../../services/editor.service";
import { SyncService } from "../../services/sync.service";
import { PresenterCanvasComponent } from "../presenter-canvas/presenter-canvas.component";

@Component({
  selector: "app-stage",
  standalone: true,
  imports: [CommonModule, PresenterCanvasComponent],
  template: `
    <div class="stage-shell">
      <div class="stage-fitter" [ngStyle]="fitterStyle()">
        <div class="stage-frame" [ngStyle]="frameStyle()" (click)="onStageClick($event)">
          <ng-content></ng-content>
          <!-- 畫板與雷射筆組件放置在 stage-frame 中，與 1920x1080 簡報區域重合 -->
          <app-presenter-canvas></app-presenter-canvas>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      :host {
        position: absolute;
        inset: 0;
        display: block;
      }
      .stage-shell {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        position: relative;
      }
      .stage-fitter {
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        background-color: var(--surface, #111);
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
        position: relative;
        /* 初始用 CSS 固定比例，避免 ResizeObserver 觸發前出現縮放動畫 */
        width: 100%;
        aspect-ratio: 16 / 9;
        max-width: calc(100vh * 16 / 9);
      }
      .stage-frame {
        width: 1920px;
        height: 1080px;
        position: absolute;
        transform-origin: top left;
        top: 0;
        left: 0;
        overflow: hidden;
        /* 關閉 transition，避免初始化時由大到小的動畫 */
        transition: none;
      }
    `,
  ],
})
export class StageComponent implements OnInit, OnDestroy {
  private readonly stepper = inject(StepperService);
  private readonly editor = inject(EditorService);
  private readonly el = inject(ElementRef);
  private readonly sync = inject(SyncService);
  readonly scale = signal<number>(0); // 0 表示尚未計算
  private observer: ResizeObserver | null = null;

  readonly fitterStyle = () => {
    const s = this.scale();
    if (s === 0) return {};  // 未計算前讓 CSS 控制
    return {
      width: `${1920 * s}px`,
      height: `${1080 * s}px`,
    };
  };

  readonly frameStyle = () => {
    const s = this.scale();
    if (s === 0) return { transform: "scale(0)" };
    return { transform: `scale(${s})` };
  };

  ngOnInit() {
    this.observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width === 0 || height === 0) continue;
        const usefulW = width - 16;
        const usefulH = height - 16;
        const s = Math.min(usefulW / 1920, usefulH / 1080);
        const finalScale = Math.max(0.01, s);
        this.scale.set(finalScale);
        this.sync.scale.set(finalScale);
      }
    });
    // 觀察 :host 元素本身（現在是 display:block，會繼承父層高度）
    this.observer.observe(this.el.nativeElement);
  }

  ngOnDestroy() {
    if (this.observer) {
      this.observer.disconnect();
    }
  }

  onStageClick(e: MouseEvent) {
    // 編輯模式與講師模式下不換頁
    if (this.editor.isEditing() || this.sync.isPresenter()) return;
    const target = e.target as HTMLElement;
    if (target.closest("button, a, input, textarea, [data-no-advance]") || target.isContentEditable) {
      return;
    }
    this.stepper.next();
  }
}
