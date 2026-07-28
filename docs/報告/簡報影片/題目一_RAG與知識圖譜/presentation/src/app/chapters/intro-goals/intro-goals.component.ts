import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-intro-goals",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-goals.component.html",
  styleUrls: ["./intro-goals.component.css"],
})
export class IntroGoalsComponent {
  readonly step = input.required<number>();

  readonly goals = [
    "驗證 KG-BFS 在多跳推理任務上，是否優於當代強化版 RAG。",
    "驗證多知識庫場景下，輕量路由能不能降低延遲，同時維持準確率。",
    "驗證自我精煉跟來源回補，能不能降低幻覺、提升可追溯性。",
    "延伸評估三元組關係標準化、實體別名消解、時序更新、Hub Node 剪枝。",
  ];

  readonly showIntro = () => this.step() === 0;

  goalState(i: number): "hidden" | "active" | "dim" {
    const s = this.step();
    const idx = s - 1; // step1 -> goal0
    if (s === 0) return "hidden";
    if (i > idx) return "hidden";
    if (i === idx) return "active";
    return "dim";
  }

  readonly showClose = () => this.step() === 4;
}
