import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-intro-rq2",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-rq2.component.html",
  styleUrls: ["./intro-rq2.component.css"],
})
export class IntroRq2Component {
  readonly step = input.required<number>();
}
