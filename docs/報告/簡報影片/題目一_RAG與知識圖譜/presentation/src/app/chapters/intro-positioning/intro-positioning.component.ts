import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-intro-positioning",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-positioning.component.html",
  styleUrls: ["./intro-positioning.component.css"],
})
export class IntroPositioningComponent {
  readonly step = input.required<number>();

  readonly outline = ["研究背景", "問題缺口", "研究目標", "研究問題", "研究載體"];

  readonly keywords = [
    { ord: "01", label: "SVO 知識圖譜" },
    { ord: "02", label: "KG-BFS 圖遍歷" },
    { ord: "03", label: "多知識庫路由" },
  ];
}
