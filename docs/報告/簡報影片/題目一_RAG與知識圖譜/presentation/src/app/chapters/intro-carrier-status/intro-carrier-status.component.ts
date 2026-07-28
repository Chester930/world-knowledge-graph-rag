import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

interface Carrier {
  label: string;
  rq: string;
}

@Component({
  selector: "app-intro-carrier-status",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-carrier-status.component.html",
  styleUrls: ["./intro-carrier-status.component.css"],
})
export class IntroCarrierStatusComponent {
  readonly step = input.required<number>();

  readonly carriers: Carrier[] = [
    { label: "SVO 抽取與驗證", rq: "支撐 RQ4，也支撐整個圖譜品質" },
    { label: "Neo4j 知識圖譜", rq: "支撐 RQ1 的 KG-BFS" },
    { label: "概念節點路由", rq: "支撐 RQ2 的多知識庫路由" },
    { label: "BFS 圖遍歷", rq: "支撐 RQ1 的多跳推理檢索" },
    { label: "自我精煉迴圈", rq: "支撐 RQ3 的幻覺降低與來源回補" },
    { label: "實驗紀錄與可追溯性規範", rq: "支撐正式論文的實驗設計" },
  ];

  readonly facts = [
    "後端骨架已經建立",
    "路由到服務到儲存庫的分層已經接好",
    "Neo4j 連線、設定、provider 工廠都有基礎",
    "前端有基本聊天室、KG 側欄、暫存區與 API 串接骨架",
    "核心演算法仍在重整與逐步實作中（SVO 抽取 / 概念節點路由 / BFS / 自我精煉）",
  ];

  rowState(i: number): "hidden" | "active" | "dim" {
    const s = this.step();
    if (s < i) return "hidden";
    if (s === i) return "active";
    return "dim";
  }

  readonly showStatus = () => this.step() === 6;
  readonly showClose = () => this.step() === 7;
}
