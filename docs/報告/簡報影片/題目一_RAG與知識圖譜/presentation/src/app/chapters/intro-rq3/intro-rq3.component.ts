import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-intro-rq3",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-rq3.component.html",
  styleUrls: ["./intro-rq3.component.css"],
})
export class IntroRq3Component {
  readonly step = input.required<number>();
}
