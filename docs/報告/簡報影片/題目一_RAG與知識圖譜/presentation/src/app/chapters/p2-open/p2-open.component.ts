import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-p2-open",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./p2-open.component.html",
  styleUrls: ["./p2-open.component.css"],
})
export class P2OpenComponent {
  readonly step = input.required<number>();
}
