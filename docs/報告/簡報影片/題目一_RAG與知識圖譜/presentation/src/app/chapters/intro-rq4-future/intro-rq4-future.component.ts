import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-intro-rq4-future",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-rq4-future.component.html",
  styleUrls: ["./intro-rq4-future.component.css"],
})
export class IntroRq4FutureComponent {
  readonly step = input.required<number>();
}
