import { Type } from "@angular/core";

export interface ChapterStepProps {
  step: number; // 0..(narrations.length - 1)
}

export type Narration = string;

export interface ChapterDef {
  id: string;
  title: string;
  /**
   * Per-step narration text. **Length === total steps in this chapter.**
   */
  narrations: Narration[];
  layout: any;
  component: Type<any>;
}
