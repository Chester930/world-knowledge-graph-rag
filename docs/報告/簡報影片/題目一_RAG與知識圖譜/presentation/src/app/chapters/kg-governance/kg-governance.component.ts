import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-kg-governance",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./kg-governance.component.html",
  styleUrls: ["./kg-governance.component.css"],
})
export class KgGovernanceComponent {
  readonly step = input.required<number>();
  readonly items = [
    ["LLM 抽取", "降低建圖門檻"],
    ["受控詞彙", "穩定關係類型"],
    ["實體對齊", "避免節點碎片"],
    ["來源追溯", "每條邊回原文"],
    ["增量更新", "新資料不重建"],
    ["遍歷控制", "避免路徑爆炸"],
    ["向量接圖", "自然語言入口"],
  ];
  state(i: number): string {
    if (this.step() < 2 || this.step() > 8) return "idle";
    const active = this.step() - 2;
    if (i === active) return "active";
    if (i < active) return "past";
    return "idle";
  }
}
