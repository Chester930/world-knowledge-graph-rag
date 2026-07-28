import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

interface Check {
  title: string;
  detail: string;
}

@Component({
  selector: "app-p2-verification-stack",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./p2-verification-stack.component.html",
  styleUrls: ["./p2-verification-stack.component.css"],
})
export class P2VerificationStackComponent {
  readonly step = input.required<number>();

  readonly checks: Check[] = [
    { title: "格式", detail: "主詞、關係、受詞與 citation 欄位必須完整。" },
    { title: "關係詞彙", detail: "rel_type 必須落在受控清單，避免同義關係分裂。" },
    { title: "語意方向", detail: "主詞與受詞不能反，關係不能超出原文可支持範圍。" },
    { title: "來源", detail: "每條邊要回到文件、chunk 與句子範圍。" },
    { title: "去重", detail: "相同事實合併成一條邊，來源清單累加。" },
    { title: "路徑", detail: "多個三元組串起來後，仍要能支撐推理鏈。" },
  ];

  state(index: number): "active" | "past" | "idle" {
    const active = this.step() - 1;
    if (this.step() === 0 || this.step() === 7) return "idle";
    if (index === active) return "active";
    if (index < active) return "past";
    return "idle";
  }

  activeCheck(): Check {
    return this.checks[Math.max(0, Math.min(this.checks.length - 1, this.step() - 1))]!;
  }
}
