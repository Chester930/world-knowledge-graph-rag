import "zone.js";
import "./styles/base.css";
import "./styles/animations.css";
import "./styles/fonts.css";
import "./styles/tokens.css";
import { bootstrapApplication } from "@angular/platform-browser";
import { AppComponent } from "./app/app.component";

bootstrapApplication(AppComponent).catch((err) => console.error(err));
