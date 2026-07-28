import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-intro-rq-overview",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./intro-rq-overview.component.html",
  styleUrls: ["./intro-rq-overview.component.css"],
})
export class IntroRqOverviewComponent {
  readonly step = input.required<number>();

  readonly rqs = [
    { id: "RQ1", tier: "core" },
    { id: "RQ2", tier: "core" },
    { id: "RQ3", tier: "core" },
    { id: "RQ4", tier: "bridge" },
    { id: "RQ5", tier: "future" },
    { id: "RQ6", tier: "future" },
  ];

  readonly framework = ["理論基礎", "實踐基礎", "本專案落點"];
}
