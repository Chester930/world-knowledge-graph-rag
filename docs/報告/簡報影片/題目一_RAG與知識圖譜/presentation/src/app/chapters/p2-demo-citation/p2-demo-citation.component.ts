import { Component, input } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-p2-demo-citation",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./p2-demo-citation.component.html",
  styleUrls: ["./p2-demo-citation.component.css"],
})
export class P2DemoCitationComponent {
  readonly step = input.required<number>();

  readonly triple = {
    subject: "勞動基準法第三十六條第四項指定行業",
    relation: "DEFINED_AS",
    object: "經目的事業主管機關同意與勞動部指定之行業，得於每七日週期內調整例假",
  };
}
