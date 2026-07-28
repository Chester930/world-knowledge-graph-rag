import { Injectable, inject, signal, effect } from "@angular/core";
import { StepperService } from "./stepper.service";

export interface DrawPoint {
  x: number;
  y: number;
}

export interface DrawStroke {
  color: string;
  width: number;
  points: DrawPoint[];
}

export interface LaserPos {
  x: number;
  y: number;
  visible: boolean;
  size?: number;
}

function checkIsPresenter(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("presenter") === "1";
}

@Injectable({
  providedIn: "root",
})
export class SyncService {
  private readonly stepper = inject(StepperService);

  readonly isPresenter = signal<boolean>(checkIsPresenter());
  readonly laserPos = signal<LaserPos>({ x: 0, y: 0, visible: false });
  readonly scale = signal<number>(1); // 👈 全域縮放比例，由 Stage 寫入，由 Canvas 讀取

  // 用於通知 Canvas 繪圖的 Event Signals
  readonly drawEvents = signal<{
    type: "start" | "draw" | "end" | "clear" | "undo" | "tool-change";
    data?: any;
  } | null>(null);

  private channel!: BroadcastChannel;

  constructor() {
    if (typeof window !== "undefined") {
      this.channel = new BroadcastChannel("presenter-sync-channel");

      // 監聽來自其他視窗的同步訊號
      this.channel.onmessage = (event) => {
        const msg = event.data;
        if (!msg) return;

        // 如果當前是觀眾端（非講師），則接收講師端的指令
        if (!this.isPresenter()) {
          switch (msg.type) {
            case "page-change":
              this.stepper.cursor.set({ chapter: msg.chapter, step: msg.step });
              break;
            case "laser-move":
              this.laserPos.set(msg.pos);
              break;
            case "draw-start":
              this.drawEvents.set({ type: "start", data: msg.data });
              break;
            case "draw-draw":
              this.drawEvents.set({ type: "draw", data: msg.data });
              break;
            case "draw-end":
              this.drawEvents.set({ type: "end" });
              break;
            case "draw-clear":
              this.drawEvents.set({ type: "clear" });
              break;
            case "draw-undo":
              this.drawEvents.set({ type: "undo" });
              break;
          }
        }
      };

      // 監聽 Stepper 狀態，若是講師端，翻頁時自動廣播給觀眾
      effect(() => {
        const cur = this.stepper.cursor();
        if (this.isPresenter()) {
          this.channel.postMessage({
            type: "page-change",
            chapter: cur.chapter,
            step: cur.step,
          });
        }
      });
    }
  }

  // 廣播雷射筆位置
  broadcastLaser(pos: LaserPos) {
    if (this.isPresenter() && this.channel) {
      this.laserPos.set(pos);
      this.channel.postMessage({
        type: "laser-move",
        pos,
      });
    }
  }

  // 廣播畫筆繪製動作
  broadcastDraw(type: "start" | "draw" | "end" | "clear" | "undo", data?: any) {
    if (this.isPresenter() && this.channel) {
      this.channel.postMessage({
        type: `draw-${type === "start" || type === "draw" ? type : type === "end" ? "end" : type === "clear" ? "clear" : "undo"}`,
        data,
      });
    }
  }
}
