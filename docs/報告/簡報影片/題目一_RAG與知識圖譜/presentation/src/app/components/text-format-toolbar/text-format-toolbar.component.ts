import { Component, inject, signal, OnDestroy } from "@angular/core";
import { CommonModule } from "@angular/common";
import { EditorService } from "../../services/editor.service";

interface ToolbarPos {
  top: number;
  left: number;
  visible: boolean;
}

@Component({
  selector: "app-text-format-toolbar",
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (pos().visible && editor.isEditing()) {
      <div
        class="format-toolbar"
        [style.top.px]="pos().top"
        [style.left.px]="pos().left"
        (mousedown)="$event.preventDefault()"
      >
        <!-- 粗體 / 斜體 -->
        <button class="fmt-btn" (click)="exec('bold')" title="粗體 Ctrl+B"><b>B</b></button>
        <button class="fmt-btn fmt-italic" (click)="exec('italic')" title="斜體 Ctrl+I"><i>I</i></button>

        <div class="fmt-sep"></div>

        <!-- 字型大小 -->
        <button class="fmt-btn size-btn" (click)="setSize('32px')" title="32px">32</button>
        <button class="fmt-btn size-btn" (click)="setSize('48px')" title="48px">48</button>
        <button class="fmt-btn size-btn" (click)="setSize('64px')" title="64px">64</button>
        <button class="fmt-btn size-btn" (click)="setSize('80px')" title="80px">80</button>
        <button class="fmt-btn size-btn" (click)="setSize('96px')" title="96px">96</button>

        <div class="fmt-sep"></div>

        <!-- 顏色：Token-based，換主題自動跟著變 -->
        <button class="fmt-btn color-btn" [ngStyle]="{background: resolveToken('--accent'   )}" (click)="setTokenColor('--accent'   )" title="accent（強調色）"></button>
        <button class="fmt-btn color-btn" [ngStyle]="{background: resolveToken('--text'     )}" (click)="setTokenColor('--text'     )" title="text（主文字色）"></button>
        <button class="fmt-btn color-btn" [ngStyle]="{background: resolveToken('--text-2'   )}" (click)="setTokenColor('--text-2'   )" title="text-2（副文字色）"></button>
        <button class="fmt-btn color-btn" [ngStyle]="{background: resolveToken('--text-mute')}" (click)="setTokenColor('--text-mute')" title="text-mute（靜音色）"></button>
      </div>
    }
  `,
  styles: [
    `
    .format-toolbar {
      position: fixed;
      z-index: 99999;
      background: rgba(10, 15, 10, 0.97);
      border: 1px solid rgba(0, 255, 136, 0.3);
      border-radius: 10px;
      padding: 6px 10px;
      display: flex;
      align-items: center;
      gap: 4px;
      box-shadow: 0 12px 40px rgba(0,0,0,0.7), 0 0 0 1px rgba(0,255,136,0.05);
      backdrop-filter: blur(12px);
      /* 顯示在選取範圍正上方 */
      transform: translate(-50%, calc(-100% - 10px));
      pointer-events: auto;
      user-select: none;
    }
    .format-toolbar::after {
      content: '';
      position: absolute;
      bottom: -6px;
      left: 50%;
      transform: translateX(-50%);
      width: 0;
      height: 0;
      border-left: 6px solid transparent;
      border-right: 6px solid transparent;
      border-top: 6px solid rgba(0, 255, 136, 0.3);
    }
    .fmt-btn {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.12);
      color: #e0ffe0;
      padding: 4px 8px;
      border-radius: 5px;
      cursor: pointer;
      font-size: 0.78rem;
      min-width: 28px;
      height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
      font-family: inherit;
    }
    .fmt-btn:hover {
      background: rgba(0,255,136,0.15);
      border-color: rgba(0,255,136,0.4);
      color: #00ff88;
      transform: translateY(-1px);
    }
    .fmt-italic { font-style: italic; }
    .size-btn {
      font-size: 0.7rem;
      font-weight: 600;
      letter-spacing: -0.5px;
      min-width: 32px;
    }
    .color-btn {
      width: 22px;
      height: 22px;
      min-width: 22px;
      padding: 0;
      border-radius: 50%;
      border: 2px solid rgba(255,255,255,0.25);
    }
    .color-btn:hover {
      border-color: #fff;
      transform: scale(1.25) translateY(0);
    }
    .fmt-sep {
      width: 1px;
      height: 18px;
      background: rgba(255,255,255,0.12);
      margin: 0 2px;
      flex-shrink: 0;
    }
    `,
  ],
})
export class TextFormatToolbarComponent implements OnDestroy {
  readonly editor = inject(EditorService);
  readonly pos = signal<ToolbarPos>({ top: 0, left: 0, visible: false });

  constructor() {
    if (typeof document !== "undefined") {
      document.addEventListener("selectionchange", this.onSelectionChange);
    }
  }

  ngOnDestroy() {
    if (typeof document !== "undefined") {
      document.removeEventListener("selectionchange", this.onSelectionChange);
    }
  }

  private onSelectionChange = () => {
    if (!this.editor.isEditing()) {
      this.pos.set({ top: 0, left: 0, visible: false });
      return;
    }

    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.toString().trim() === "") {
      this.pos.set({ top: 0, left: 0, visible: false });
      return;
    }

    // 只在 contenteditable 內的選取才顯示
    const anchor = sel.anchorNode;
    const el = (anchor instanceof Element ? anchor : anchor?.parentElement) as HTMLElement | null;
    if (!el?.closest("[contenteditable]")) {
      this.pos.set({ top: 0, left: 0, visible: false });
      return;
    }

    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return;

    this.pos.set({
      top: rect.top,
      left: rect.left + rect.width / 2,
      visible: true,
    });
  };

  exec(command: string) {
    document.execCommand(command, false);
  }

  setSize(px: string) {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    // 用 span 包住選取的文字，設定 font-size
    document.execCommand(
      "insertHTML",
      false,
      `<span style="font-size:${px};line-height:1.2">${sel.toString()}</span>`,
    );
  }

  setColor(color: string) {
    // execCommand foreColor 用 hex/rgba 都可以
    document.execCommand("foreColor", false, color);
  }

  /** 解析 CSS 變數為實際顏色值後套用，換主題時自動對應 */
  setTokenColor(token: string) {
    const resolved = this.resolveToken(token);
    if (resolved) {
      document.execCommand("foreColor", false, resolved);
    }
  }

  /** 讓 template 用來動態顯示按鈕背景色 */
  resolveToken(token: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(token).trim() || '#888';
  }
}
