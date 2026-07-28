import { Component, inject, computed } from "@angular/core";
import { CommonModule } from "@angular/common";
import { StepperService } from "../../services/stepper.service";

@Component({
  selector: "app-progress-bar",
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="progress-container" data-no-advance>
      <div
        *ngFor="let step of steps(); let idx = index"
        class="progress-segment"
        [class.active]="idx === activeIdx()"
        (click)="jump(idx)"
      ></div>
    </div>
  `,
  styles: [
    `
      .progress-container {
        position: fixed;
        bottom: 0;
        left: 0;
        width: 100%;
        height: 6px;
        display: flex;
        gap: 3px;
        padding: 2px 4px;
        background: rgba(0, 0, 0, 0.5);
        opacity: 0;
        transition:
          opacity 0.2s ease,
          height 0.2s ease;
        z-index: 10000;
      }
      .progress-container:hover {
        opacity: 1;
        height: 10px;
      }
      .progress-segment {
        flex: 1;
        height: 100%;
        background: rgba(255, 255, 255, 0.25);
        cursor: pointer;
        border-radius: 1px;
      }
      .progress-segment.active {
        background: var(--accent, #00ff88);
      }
      .progress-segment:hover {
        background: rgba(255, 255, 255, 0.6);
      }
    `,
  ],
})
export class ProgressBarComponent {
  private readonly stepper = inject(StepperService);

  readonly steps = computed(() => Array(this.stepper.totalGlobal()).fill(0));

  readonly activeIdx = computed(() => this.stepper.globalIndex());

  jump(idx: number) {
    this.stepper.jumpToGlobal(idx);
  }
}
