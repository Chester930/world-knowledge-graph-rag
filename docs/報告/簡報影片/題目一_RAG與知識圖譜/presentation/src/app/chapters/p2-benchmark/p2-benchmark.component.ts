import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-p2-benchmark",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./p2-benchmark.component.html",
  styleUrls: ["./p2-benchmark.component.css"],
})
export class P2BenchmarkComponent {
  readonly step = input.required<number>();

  readonly rows = [
    { mode: "純 RAG", structure: "文字片段", risk: "有相關文字，但沒有明確關係表", status: "NO_TRIPLES" },
    { mode: "未驗證 SVO", structure: "候選 triples", risk: "可能方向錯、關係詞混亂、來源缺失", status: "PARTIAL" },
    { mode: "驗證後 SVO", structure: "可信 triples", risk: "可比對 gold triples 與來源句", status: "PASS" },
  ];
}
