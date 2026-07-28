import { Directive, ElementRef, Input, OnInit, OnDestroy, inject, effect } from "@angular/core";
import { EditorService } from "../services/editor.service";

@Directive({
  selector: "[appDragResize]",
  standalone: true,
})
export class DragResizeDirective implements OnInit, OnDestroy {
  private readonly el = inject(ElementRef);
  private readonly editor = inject(EditorService);

  @Input("appDragResize") blockId!: string;
  @Input() step!: number;

  private handleEl: HTMLDivElement | null = null;
  private isDragging = false;
  private isResizing = false;

  private startX = 0;
  private startY = 0;
  private startLeft = 0;
  private startTop = 0;
  private startWidth = 0;
  private startHeight = 0;

  constructor() {
    effect(() => {
      const active = this.editor.isEditing();
      const dom = this.el.nativeElement as HTMLElement;
      if (active) {
        dom.style.cursor = "move";
        this.addResizeHandle();
      } else {
        dom.style.outline = "none";
        dom.style.cursor = "default";
        this.removeResizeHandle();
      }
    });
  }

  ngOnInit() {
    const dom = this.el.nativeElement as HTMLElement;
    dom.addEventListener("mousedown", this.onMouseDown);
  }

  ngOnDestroy() {
    const dom = this.el.nativeElement as HTMLElement;
    dom.removeEventListener("mousedown", this.onMouseDown);
    this.removeResizeHandle();
  }

  private getScale(): number {
    const frame = document.querySelector(".stage-frame") as HTMLElement;
    if (frame) {
      const match = frame.style.transform.match(/scale\(([^)]+)\)/);
      if (match) return parseFloat(match[1]);
    }
    return 1;
  }

  private addResizeHandle() {
    if (this.handleEl) return;
    const dom = this.el.nativeElement as HTMLElement;

    const computedStyle = window.getComputedStyle(dom);
    if (computedStyle.position === "static") {
      dom.style.position = "absolute";
    }

    this.handleEl = document.createElement("div");
    const h = this.handleEl;
    h.style.position = "absolute";
    h.style.right = "-4px";
    h.style.bottom = "-4px";
    h.style.width = "16px";
    h.style.height = "16px";
    h.style.backgroundColor = "var(--accent)";
    h.style.cursor = "se-resize";
    h.style.zIndex = "9999";
    h.style.borderRadius = "3px";
    h.title = "拖曳調整大小";

    h.addEventListener("mousedown", this.onHandleMouseDown);
    dom.appendChild(h);
  }

  private removeResizeHandle() {
    if (this.handleEl) {
      this.handleEl.removeEventListener("mousedown", this.onHandleMouseDown);
      this.handleEl.remove();
      this.handleEl = null;
    }
  }

  private isEditableTarget(target: EventTarget | null): boolean {
    if (!target) return false;
    const el = target as HTMLElement;
    if (el.isContentEditable) return true;
    if (el.closest("[contenteditable='true'], [contenteditable='']")) return true;
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT") return true;
    return false;
  }

  private onMouseDown = (e: MouseEvent) => {
    if (!this.editor.isEditing()) return;
    if (e.target === this.handleEl) return;

    // 點在可編輯文字上 → 放行，讓 contenteditable 正常 focus
    if (this.isEditableTarget(e.target)) return;

    // 非文字區域才啟動拖曳
    e.preventDefault();
    e.stopPropagation();

    this.isDragging = true;
    this.startX = e.clientX;
    this.startY = e.clientY;

    const dom = this.el.nativeElement as HTMLElement;
    this.startLeft = dom.offsetLeft;
    this.startTop = dom.offsetTop;

    document.addEventListener("mousemove", this.onMouseMove);
    document.addEventListener("mouseup", this.onMouseUp);
  };

  private onHandleMouseDown = (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    this.isResizing = true;
    this.startX = e.clientX;
    this.startY = e.clientY;

    const dom = this.el.nativeElement as HTMLElement;
    this.startWidth = dom.offsetWidth;
    this.startHeight = dom.offsetHeight;

    document.addEventListener("mousemove", this.onMouseMove);
    document.addEventListener("mouseup", this.onMouseUp);
  };

  private onMouseMove = (e: MouseEvent) => {
    const scale = this.getScale();
    const deltaX = (e.clientX - this.startX) / scale;
    const deltaY = (e.clientY - this.startY) / scale;

    if (this.isDragging) {
      const nextX = Math.round(this.startLeft + deltaX);
      const nextY = Math.round(this.startTop + deltaY);

      this.editor.updateBlockLayout(this.step, this.blockId, { x: nextX, y: nextY });
    } else if (this.isResizing) {
      const nextW = Math.max(30, Math.round(this.startWidth + deltaX));
      const nextH = Math.max(20, Math.round(this.startHeight + deltaY));

      this.editor.updateBlockLayout(this.step, this.blockId, { w: nextW, h: nextH });
    }
  };

  private onMouseUp = () => {
    this.isDragging = false;
    this.isResizing = false;
    document.removeEventListener("mousemove", this.onMouseMove);
    document.removeEventListener("mouseup", this.onMouseUp);
  };
}
