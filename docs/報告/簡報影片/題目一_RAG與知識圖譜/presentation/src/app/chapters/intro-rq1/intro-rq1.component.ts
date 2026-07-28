import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-intro-rq1",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-rq1.component.html",
  styleUrls: ["./intro-rq1.component.css"],
})
export class IntroRq1Component {
  readonly step = input.required<number>();
}
