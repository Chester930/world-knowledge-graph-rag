import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

interface Scenario {
  id: number;
  topic: string;
  kg: string;
  result: "hit" | "partial" | "limit";
}

@Component({
  selector: "app-p2-demo-qa",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./p2-demo-qa.component.html",
  styleUrls: ["./p2-demo-qa.component.css"],
})
export class P2DemoQaComponent {
  readonly step = input.required<number>();

  readonly scenarios: Scenario[] = [
    { id: 1, topic: "飛航值勤上限", kg: "排班", result: "hit" },
    { id: 2, topic: "住院醫師排班", kg: "排班", result: "hit" },
    { id: 3, topic: "保全 84-1", kg: "排班", result: "partial" },
    { id: 4, topic: "台鐵輪班間隔", kg: "排班", result: "hit" },
    { id: 5, topic: "生理假規定", kg: "排班", result: "hit" },
    { id: 6, topic: "例假調整特例", kg: "排班", result: "hit" },
    { id: 7, topic: "颱風天工資", kg: "薪資", result: "hit" },
    { id: 8, topic: "試用期工資", kg: "薪資", result: "hit" },
    { id: 9, topic: "產假全勤獎金", kg: "薪資", result: "limit" },
    { id: 10, topic: "安全帽違規", kg: "薪資", result: "hit" },
  ];

  resultLabel(result: Scenario["result"]): string {
    return result === "hit" ? "命中" : result === "partial" ? "部分" : "路由限制";
  }
}
