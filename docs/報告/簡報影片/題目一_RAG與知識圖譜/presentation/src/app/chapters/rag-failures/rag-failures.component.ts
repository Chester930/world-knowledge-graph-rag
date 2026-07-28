import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

interface Failure {
  title: string;
  short: string;
  detail: string;
}

@Component({
  selector: "app-rag-failures",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./rag-failures.component.html",
  styleUrls: ["./rag-failures.component.css"],
})
export class RagFailuresComponent {
  readonly step = input.required<number>();

  readonly failures: Failure[] = [
    { title: "精確詞漏失", short: "dense blind spot", detail: "法條、人名、型號抓不準字面命中。" },
    { title: "排序不準", short: "top-k rank", detail: "相關片段不一定能正確支撐答案。" },
    { title: "檢索漂移", short: "retrieval drift", detail: "多步查詢沿著錯證據走偏。" },
    { title: "資料源路由", short: "routing", detail: "選對知識庫，不等於內部關係正確。" },
    { title: "補查成本", short: "active RAG", detail: "再查能補證據，也會引入延遲與噪音。" },
    { title: "引用不支撐", short: "citation ≠ entailment", detail: "有引用，不代表結論真的被支持。" },
    { title: "切塊粒度", short: "chunk granularity", detail: "句子更精準，但仍不是 typed relation。" },
  ];

  itemState(index: number): "idle" | "active" | "past" {
    const active = this.step() - 1;
    if (this.step() === 0 || this.step() === 8) return "idle";
    if (index === active) return "active";
    if (index < active) return "past";
    return "idle";
  }

  activeFailure(): Failure {
    return this.failures[Math.max(0, Math.min(6, this.step() - 1))]!;
  }
}
