import { Component, input, computed } from "@angular/core";
import { CommonModule } from "@angular/common";

interface DefRow {
  key: string;
  ord: string;
  label: string;
  def: string;
}

@Component({
  selector: "app-coldopen",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./coldopen.component.html",
  styleUrls: ["./coldopen.component.css"],
})
export class ColdopenComponent {
  readonly step = input.required<number>();

  readonly rows: DefRow[] = [
    { key: "rag", ord: "01", label: "RAG", def: "查詢的當下，去文字裡篩證據。" },
    { key: "kg", ord: "02", label: "知識圖譜", def: "資料一進來，就先把關係提煉出來。" },
    { key: "graphrag", ord: "03", label: "GraphRAG", def: "在提煉後的關係上檢索，再回原文驗證一次。" },
  ];

  // step 2 -> row0 active, step 3 -> row1 active, step 4 -> row2 active
  rowState(i: number): "hidden" | "active" | "dim" {
    const s = this.step();
    const activeIndex = s - 2;
    if (s < 2) return "hidden";
    if (i > activeIndex) return "hidden";
    if (i === activeIndex) return "active";
    return "dim";
  }

  readonly showTitle = computed(() => this.step() === 0);
  readonly showQuestion = computed(() => this.step() === 1);
  readonly showRows = computed(() => this.step() >= 2 && this.step() <= 4);
  readonly showClose = computed(() => this.step() === 5);
}
