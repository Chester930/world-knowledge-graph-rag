import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-notebook-rag",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./notebook-rag.component.html",
  styleUrls: ["./notebook-rag.component.css"],
})
export class NotebookRagComponent {
  readonly step = input.required<number>();

  readonly flow = ["資料來源", "檢索證據", "LLM 整理", "來源引用"];
  readonly pipeline = ["解析", "切分", "索引", "提問", "檢索", "上下文", "生成", "引用"];

  activeFlow(i: number): boolean {
    return this.step() >= 2 && i <= Math.min(3, this.step() - 2);
  }
}
