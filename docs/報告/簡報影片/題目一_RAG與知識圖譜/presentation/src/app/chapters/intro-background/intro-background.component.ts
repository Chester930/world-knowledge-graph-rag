import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

interface Layer {
  ord: string;
  label: string;
  detail: string;
}

@Component({
  selector: "app-intro-background",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-background.component.html",
  styleUrls: ["./intro-background.component.css"],
})
export class IntroBackgroundComponent {
  readonly step = input.required<number>();

  readonly layers: Layer[] = [
    { ord: "01", label: "LLM 的限制", detail: "靜態知識、幻覺、推理路徑不透明。" },
    { ord: "02", label: "RAG 的補強與邊界", detail: "以文字 chunk 為檢索單位，關係、多跳路徑、可追溯仍不足。" },
    { ord: "03", label: "GraphRAG 的機會與缺陷", detail: "建圖成本高、品質不穩、偏全局摘要、路徑爆炸、評估困難。" },
  ];

  layerState(i: number): "hidden" | "active" | "dim" {
    const s = this.step();
    if (s < i) return "hidden";
    if (s === i) return "active";
    return "dim";
  }

  readonly showClose = () => this.step() === 3;
}
