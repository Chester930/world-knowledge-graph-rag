import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-problem-one-close",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./problem-one-close.component.html",
  styleUrls: ["./problem-one-close.component.css"],
})
export class ProblemOneCloseComponent {
  readonly step = input.required<number>();
}
