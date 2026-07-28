import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-svo-proof",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./svo-proof.component.html",
  styleUrls: ["./svo-proof.component.css"],
})
export class SvoProofComponent {
  readonly step = input.required<number>();
  readonly checks = ["完整性", "關係類型", "方向", "語意支持", "來源追溯", "去重", "推理鏈"];
}
