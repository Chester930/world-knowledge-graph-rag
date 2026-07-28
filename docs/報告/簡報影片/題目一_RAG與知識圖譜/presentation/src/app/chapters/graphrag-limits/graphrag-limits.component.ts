import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-graphrag-limits",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./graphrag-limits.component.html",
  styleUrls: ["./graphrag-limits.component.css"],
})
export class GraphragLimitsComponent {
  readonly step = input.required<number>();
  readonly limits = ["冷啟動成本", "錯誤路徑", "偏全局摘要", "路徑爆炸", "評估困難"];
  state(i: number): string {
    if (this.step() < 1 || this.step() > 5) return "idle";
    return i === this.step() - 1 ? "active" : i < this.step() - 1 ? "past" : "idle";
  }
}
