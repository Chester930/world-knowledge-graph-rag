import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-kg-core",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./kg-core.component.html",
  styleUrls: ["./kg-core.component.css"],
})
export class KgCoreComponent {
  readonly step = input.required<number>();
  readonly flow = ["解析", "切句", "實體", "關係", "三元組", "對齊", "去重", "來源", "路徑"];
}
