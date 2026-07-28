import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

interface Gap {
  gap: string;
  direction: string;
}

@Component({
  selector: "app-intro-gaps",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-gaps.component.html",
  styleUrls: ["./intro-gaps.component.css"],
})
export class IntroGapsComponent {
  readonly step = input.required<number>();

  readonly gaps: Gap[] = [
    { gap: "多跳推理不穩", direction: "KG-BFS 圖遍歷" },
    { gap: "多知識庫可擴展性不足", direction: "概念節點輕量路由" },
    { gap: "幻覺與來源不明", direction: "自我精煉與來源回補" },
    { gap: "關係語意不一致", direction: "受控關係詞彙與 SVO 驗證" },
    { gap: "實體重複與指代問題", direction: "實體別名與指代消解" },
    { gap: "Hub Node 路徑爆炸", direction: "向量引導剪枝" },
  ];

  rowState(i: number): "hidden" | "active" | "dim" {
    const s = this.step();
    if (s < i) return "hidden";
    if (s === i) return "active";
    return "dim";
  }
}
