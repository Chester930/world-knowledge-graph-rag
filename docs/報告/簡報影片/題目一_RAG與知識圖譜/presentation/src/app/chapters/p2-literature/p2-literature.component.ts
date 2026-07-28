import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

interface Source {
  name: string;
  proof: string;
}

@Component({
  selector: "app-p2-literature",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./p2-literature.component.html",
  styleUrls: ["./p2-literature.component.css"],
})
export class P2LiteratureComponent {
  readonly step = input.required<number>();

  readonly sources: Source[] = [
    { name: "OpenIE", proof: "relation triples 是資訊抽取的基礎形式。" },
    { name: "Text2KGBench", proof: "KG 生成需要 benchmark 與 metrics，不是主觀看起來合理。" },
    { name: "CORE-KG", proof: "LLM 建圖會遇到 hallucination、duplicate nodes、noisy graph。" },
    { name: "CoDe-KG", proof: "句子分解與指代消解會影響 relation extraction 品質。" },
    { name: "Robust GraphRAG", proof: "錯誤 KG 會造成 retrieval drift 與 hallucination。" },
  ];

  sourceState(index: number): "active" | "past" | "idle" {
    const active = this.step() - 1;
    if (this.step() === 0 || this.step() === 6) return "idle";
    if (index === active) return "active";
    if (index < active) return "past";
    return "idle";
  }

  activeSource(): Source {
    return this.sources[Math.max(0, Math.min(this.sources.length - 1, this.step() - 1))]!;
  }
}
