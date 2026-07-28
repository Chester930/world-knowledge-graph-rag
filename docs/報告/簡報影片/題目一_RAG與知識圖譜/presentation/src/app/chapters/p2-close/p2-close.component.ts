import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-p2-close",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./p2-close.component.html",
  styleUrls: ["./p2-close.component.css"],
})
export class P2CloseComponent {
  readonly step = input.required<number>();
}
