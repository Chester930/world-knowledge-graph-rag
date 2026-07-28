import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-compare-graphrag",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./compare-graphrag.component.html",
  styleUrls: ["./compare-graphrag.component.css"],
})
export class CompareGraphragComponent {
  readonly step = input.required<number>();
  readonly rows = [
    ["處理時機", "查詢時檢索", "事前建圖"],
    ["回傳單位", "chunk / 句子", "實體 / 關係 / 路徑"],
    ["強項", "快速導入 / 摘要", "關係查詢 / 多跳推理"],
  ];
}
