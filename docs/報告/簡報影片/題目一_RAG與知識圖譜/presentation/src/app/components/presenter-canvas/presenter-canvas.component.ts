import { Component, ElementRef, OnInit, OnDestroy, ViewChild, inject, signal, effect, computed } from "@angular/core";
import { CommonModule } from "@angular/common";
import { SyncService, DrawPoint, DrawStroke, LaserPos } from "../../services/sync.service";
import { StepperService } from "../../services/stepper.service";

@Component({
  selector: "app-presenter-canvas",
  standalone: true,
  imports: [CommonModule],
  template: `
    <!-- 繪圖畫布，完全覆蓋 1920x1080 簡報區域 -->
    <canvas
      #canvasRef
      width="1920"
      height="1080"
      class="presenter-canvas"
      [class.pointer-active]="tool() === 'pen' || tool() === 'eraser'"
      (mousedown)="onMouseDown($event)"
    ></canvas>

    <!-- 雷射筆發光圓點（講師與觀眾端都會同步渲染） -->
    <div
      *ngIf="laser().visible"
      class="laser-pointer"
      [style.left.px]="laser().x"
      [style.top.px]="laser().y"
    >
      <div class="laser-dot" [style.width.px]="laserSize()" [style.height.px]="laserSize()"></div>
      <div class="laser-glow" [style.width.px]="laserSize() * 4" [style.height.px]="laserSize() * 4"></div>
    </div>

    <!-- 講師控制面板：只在講師端且非編輯模式下顯示 -->
    <div class="presenter-toolbox" *ngIf="sync.isPresenter() && !editorEditing()" data-no-advance>
      <button 
        class="tool-btn" 
        [class.active]="tool() === 'mouse'"
        (click)="setTool('mouse')"
        title="滑鼠指標"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/></svg>
      </button>
      
      <button 
        class="tool-btn" 
        [class.active]="tool() === 'laser'"
        (click)="setTool('laser')"
        title="雷射筆"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="2" fill="currentColor"/></svg>
      </button>

      <div class="tool-sep"></div>

      <!-- 畫筆與顏色 -->
      <button 
        class="tool-btn color-btn" 
        [class.active]="tool() === 'pen' && penColor() === '#ffffff'"
        (click)="selectPen('#ffffff')"
        title="白色畫筆"
      >
        <span class="color-dot" style="background-color: #ffffff;"></span>
      </button>
      <button 
        class="tool-btn color-btn" 
        [class.active]="tool() === 'pen' && penColor() === '#00ff88'"
        (click)="selectPen('#00ff88')"
        title="綠色畫筆"
      >
        <span class="color-dot" style="background-color: #00ff88;"></span>
      </button>
      <button 
        class="tool-btn color-btn" 
        [class.active]="tool() === 'pen' && penColor() === '#ff3355'"
        (click)="selectPen('#ff3355')"
        title="紅色畫筆"
      >
        <span class="color-dot" style="background-color: #ff3355;"></span>
      </button>
      <button 
        class="tool-btn color-btn" 
        [class.active]="tool() === 'pen' && penColor() === '#ffff33'"
        (click)="selectPen('#ffff33')"
        title="黃色畫筆"
      >
        <span class="color-dot" style="background-color: #ffff33;"></span>
      </button>

      <!-- 工具大小選擇 -->
      <div class="tool-sep"></div>
      <button 
        class="tool-btn" 
        [class.active]="brushSize() === 3"
        (click)="brushSize.set(3)"
        title="細"
      >
        <span class="width-dot" style="width: 4px; height: 4px;"></span>
      </button>
      <button 
        class="tool-btn" 
        [class.active]="brushSize() === 8"
        (click)="brushSize.set(8)"
        title="中"
      >
        <span class="width-dot" style="width: 8px; height: 8px;"></span>
      </button>
      <button 
        class="tool-btn" 
        [class.active]="brushSize() === 16"
        (click)="brushSize.set(16)"
        title="粗"
      >
        <span class="width-dot" style="width: 14px; height: 14px;"></span>
      </button>

      <div class="tool-sep"></div>

      <!-- 橡皮擦與操作 -->
      <button 
        class="tool-btn" 
        [class.active]="tool() === 'eraser'"
        (click)="setTool('eraser')"
        title="橡皮擦"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20H7L3 16l8-8 8 8-4 4zM16 11l-5-5"/></svg>
      </button>
      
      <button class="tool-btn" (click)="undo()" title="復原 (Ctrl+Z)">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>
      </button>
      
      <button class="tool-btn" (click)="clearAll()" title="清除全部">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>
      </button>
    </div>
  `,
  styles: [
    `
      :host {
        position: absolute;
        inset: 0;
        z-index: 50; /* 覆蓋在簡報最上方，但低於頂部 nav */
        pointer-events: none;
      }
      
      .presenter-canvas {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 10;
        pointer-events: none;
      }
      
      .presenter-canvas.pointer-active {
        pointer-events: auto; /* 只有在畫筆/橡皮擦模式下才阻擋與滑鼠點擊，供寫字 */
      }
      
      /* 雷射筆發光粒子特效 */
      .laser-pointer {
        position: absolute;
        z-index: 20;
        pointer-events: none;
        transform: translate(-50%, -50%);
      }
      
      .laser-dot {
        width: 10px;
        height: 10px;
        background-color: #ff3355;
        border-radius: 50%;
        box-shadow: 0 0 6px #fff;
      }
      
      .laser-glow {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 40px;
        height: 40px;
        background: radial-gradient(circle, rgba(255, 51, 85, 0.4) 0%, rgba(255, 51, 85, 0) 70%);
        border-radius: 50%;
        animation: pulse 1.5s infinite ease-in-out;
      }
      
      @keyframes pulse {
        0%, 100% { transform: translate(-50%, -50%) scale(0.85); opacity: 0.7; }
        50% { transform: translate(-50%, -50%) scale(1.15); opacity: 1; }
      }
      
      /* 講師漂浮控制列 ( presenter toolbox ) */
      .presenter-toolbox {
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 100;
        background: rgba(10, 15, 10, 0.95);
        border: 1px solid rgba(0, 255, 136, 0.25);
        padding: 5px 8px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        gap: 6px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.6);
        pointer-events: auto;
        backdrop-filter: blur(8px);
      }
      
      .tool-btn {
        background: transparent;
        border: none;
        color: rgba(211, 240, 211, 0.6);
        width: 32px;
        height: 32px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: all 0.2s ease;
      }
      
      .tool-btn:hover {
        background: rgba(255, 255, 255, 0.05);
        color: #fff;
      }
      
      .tool-btn.active {
        background: rgba(0, 255, 136, 0.15);
        border: 1px solid rgba(0, 255, 136, 0.3);
        color: var(--accent, #00ff88);
      }
      
      .tool-sep {
        width: 1px;
        height: 18px;
        background: rgba(255, 255, 255, 0.12);
        margin: 0 2px;
      }
      
      .color-dot {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        display: inline-block;
        border: 1px solid rgba(255, 255, 255, 0.2);
        transition: transform 0.15s ease;
      }
      
      .tool-btn:hover .color-dot {
        transform: scale(1.2);
      }

      .width-dot {
        background-color: currentColor;
        border-radius: 50%;
        display: inline-block;
      }
    `,
  ],
})
export class PresenterCanvasComponent implements OnInit, OnDestroy {
  readonly sync = inject(SyncService);
  private readonly stepper = inject(StepperService);

  @ViewChild("canvasRef") canvasRef!: ElementRef<HTMLCanvasElement>;
  private ctx!: CanvasRenderingContext2D;

  readonly tool = signal<"mouse" | "laser" | "pen" | "eraser">("mouse");
  readonly penColor = signal<string>("#ffffff");
  readonly brushSize = signal<number>(8); // 預設為中等
  readonly laser = signal<LaserPos>({ x: 0, y: 0, visible: false });

  readonly laserSize = computed(() => {
    const size = this.laser().size || this.brushSize();
    if (size <= 3) return 8;
    if (size <= 8) return 14;
    return 24;
  });

  // 繪製歷史記錄（用於 undo）
  private strokes: DrawStroke[] = [];
  private currentStroke: DrawPoint[] = [];

  private isDrawing = false;
  private laserMouseMoveListener: any = null;

  // 編輯模式的輔助屬性，方便判斷
  editorEditing() {
    return typeof window !== "undefined" && 
      (window as any).angularEditorService?.isEditing?.() || false;
  }

  constructor() {
    // 監聽來自 SyncService 的雷射筆跟畫圖廣播
    effect(() => {
      const laserUpdate = this.sync.laserPos();
      if (!this.sync.isPresenter()) {
        // 觀眾端：直接套用 1920x1080 虛擬座標，雷射筆元件會自動隨 stage 縮放
        this.laser.set(laserUpdate);
      }
    }, { allowSignalWrites: true });

    // 監聽跨頁面繪圖指令
    effect(() => {
      const ev = this.sync.drawEvents();
      if (!ev || this.sync.isPresenter()) return;

      switch (ev.type) {
        case "start":
          this.remoteStartDraw(ev.data);
          break;
        case "draw":
          this.remoteDraw(ev.data);
          break;
        case "end":
          this.remoteEndDraw();
          break;
        case "clear":
          this.remoteClear();
          break;
        case "undo":
          this.remoteUndo();
          break;
      }
    });

    // 當步驟/投影片切換時，自動清除當前畫布
    effect(() => {
      this.stepper.cursor();
      this.clearAllLocal();
    });
  }

  ngOnInit() {
    if (typeof window !== "undefined" && this.sync.isPresenter()) {
      // 講師端：全域監聽滑鼠移動來追蹤雷射筆
      this.laserMouseMoveListener = (e: MouseEvent) => {
        if (this.tool() !== "laser") {
          if (this.laser().visible) {
            this.sync.broadcastLaser({ x: 0, y: 0, visible: false });
            this.laser.set({ x: 0, y: 0, visible: false });
          }
          return;
        }

        const canvas = this.canvasRef.nativeElement;
        if (!canvas) return;

        const rect = canvas.getBoundingClientRect();

        // 偵測滑鼠是否在簡報範圍內
        const mouseInFrame =
          e.clientX >= rect.left &&
          e.clientX <= rect.right &&
          e.clientY >= rect.top &&
          e.clientY <= rect.bottom;

        if (mouseInFrame) {
          // 精準換算為 1920x1080 虛擬座標
          const relX = ((e.clientX - rect.left) / rect.width) * 1920;
          const relY = ((e.clientY - rect.top) / rect.height) * 1080;

          const laserState = { x: relX, y: relY, visible: true, size: this.brushSize() };
          // 講師本機端也直接使用這個虛擬座標，因為雷射筆 div 在 1920x1080 容器內！
          this.laser.set(laserState);
          this.sync.broadcastLaser(laserState);
        } else if (this.laser().visible) {
          const emptyLaser = { x: 0, y: 0, visible: false, size: this.brushSize() };
          this.sync.broadcastLaser(emptyLaser);
          this.laser.set(emptyLaser);
        }
      };
      window.addEventListener("mousemove", this.laserMouseMoveListener);
    }
  }

  ngOnDestroy() {
    if (typeof window !== "undefined" && this.laserMouseMoveListener) {
      window.removeEventListener("mousemove", this.laserMouseMoveListener);
    }
  }

  ngAfterViewInit() {
    const canvas = this.canvasRef.nativeElement;
    this.ctx = canvas.getContext("2d")!;
    this.ctx.lineCap = "round";
    this.ctx.lineJoin = "round";
  }

  setTool(t: "mouse" | "laser" | "pen" | "eraser") {
    this.tool.set(t);
    if (t !== "laser") {
      this.laser.set({ x: 0, y: 0, visible: false });
      this.sync.broadcastLaser({ x: 0, y: 0, visible: false });
    }
  }

  selectPen(color: string) {
    this.penColor.set(color);
    this.setTool("pen");
  }

  // ─── 講師本機繪製滑鼠事件處理 ───
  onMouseDown(e: MouseEvent) {
    if (!this.sync.isPresenter()) return;
    if (this.tool() !== "pen" && this.tool() !== "eraser") return;

    e.preventDefault();
    e.stopPropagation();

    this.isDrawing = true;
    const canvas = this.canvasRef.nativeElement;
    const rect = canvas.getBoundingClientRect();

    // 換算為 1920x1080 座標
    const x = ((e.clientX - rect.left) / rect.width) * 1920;
    const y = ((e.clientY - rect.top) / rect.height) * 1080;

    this.currentStroke = [{ x, y }];

    this.ctx.beginPath();
    this.ctx.moveTo(x, y);

    const color = this.tool() === "eraser" ? "eraser" : this.penColor();
    const width = this.tool() === "eraser" ? this.brushSize() * 4 : this.brushSize();

    this.sync.broadcastDraw("start", { x, y, color, width });

    document.addEventListener("mousemove", this.onMouseMove);
    document.addEventListener("mouseup", this.onMouseUp);
  }

  private onMouseMove = (e: MouseEvent) => {
    if (!this.isDrawing) return;

    const canvas = this.canvasRef.nativeElement;
    const rect = canvas.getBoundingClientRect();

    const x = ((e.clientX - rect.left) / rect.width) * 1920;
    const y = ((e.clientY - rect.top) / rect.height) * 1080;

    this.currentStroke.push({ x, y });

    // 設定畫筆樣式
    const color = this.tool() === "eraser" ? "eraser" : this.penColor();
    const width = this.tool() === "eraser" ? this.brushSize() * 4 : this.brushSize();

    this.drawSegment(this.currentStroke[this.currentStroke.length - 2]!, { x, y }, color, width);
    this.sync.broadcastDraw("draw", { x, y });
  };

  private onMouseUp = () => {
    if (!this.isDrawing) return;
    this.isDrawing = false;

    const color = this.tool() === "eraser" ? "eraser" : this.penColor();
    const width = this.tool() === "eraser" ? this.brushSize() * 4 : this.brushSize();

    this.strokes.push({
      color,
      width,
      points: [...this.currentStroke],
    });

    this.sync.broadcastDraw("end");

    document.removeEventListener("mousemove", this.onMouseMove);
    document.removeEventListener("mouseup", this.onMouseUp);
  };

  // 繪製單個線段
  private drawSegment(p1: DrawPoint, p2: DrawPoint, color: string, width: number) {
    if (color === "eraser") {
      this.ctx.globalCompositeOperation = "destination-out"; // 疊加擦除透明
      this.ctx.lineWidth = width;
    } else {
      this.ctx.globalCompositeOperation = "source-over";
      this.ctx.strokeStyle = color;
      this.ctx.lineWidth = width;
    }

    this.ctx.beginPath();
    this.ctx.moveTo(p1.x, p1.y);
    this.ctx.lineTo(p2.x, p2.y);
    this.ctx.stroke();
  }

  // ─── 觀眾端接收廣播進行繪製 ───
  private activeRemoteStroke: DrawPoint[] = [];
  private remoteColor = "#ffffff";
  private remoteWidth = 4;

  private remoteStartDraw(data: { x: number; y: number; color: string; width: number }) {
    this.remoteColor = data.color;
    this.remoteWidth = data.width;
    this.activeRemoteStroke = [{ x: data.x, y: data.y }];
  }

  private remoteDraw(data: { x: number; y: number }) {
    if (this.activeRemoteStroke.length === 0) return;
    const p1 = this.activeRemoteStroke[this.activeRemoteStroke.length - 1]!;
    const p2 = { x: data.x, y: data.y };
    this.activeRemoteStroke.push(p2);
    this.drawSegment(p1, p2, this.remoteColor, this.remoteWidth);
  }

  private remoteEndDraw() {
    if (this.activeRemoteStroke.length > 0) {
      this.strokes.push({
        color: this.remoteColor,
        width: this.remoteWidth,
        points: [...this.activeRemoteStroke],
      });
      this.activeRemoteStroke = [];
    }
  }

  private remoteClear() {
    this.clearAllLocal();
  }

  private remoteUndo() {
    this.undoLocal();
  }

  // ─── 畫布操作工具 ───
  undo() {
    this.undoLocal();
    this.sync.broadcastDraw("undo");
  }

  private undoLocal() {
    if (this.strokes.length === 0) return;
    this.strokes.pop();
    this.redrawCanvas();
  }

  clearAll() {
    this.clearAllLocal();
    this.sync.broadcastDraw("clear");
  }

  private clearAllLocal() {
    this.strokes = [];
    if (this.ctx) {
      this.ctx.clearRect(0, 0, 1920, 1080);
    }
  }

  private redrawCanvas() {
    if (!this.ctx) return;
    this.ctx.clearRect(0, 0, 1920, 1080);
    for (const stroke of this.strokes) {
      if (stroke.points.length < 2) continue;
      for (let i = 0; i < stroke.points.length - 1; i++) {
        this.drawSegment(stroke.points[i]!, stroke.points[i + 1]!, stroke.color, stroke.width);
      }
    }
  }
}
