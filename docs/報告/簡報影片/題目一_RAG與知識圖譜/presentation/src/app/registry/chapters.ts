import type { ChapterDef } from "./types";
import { ColdopenComponent } from "../chapters/coldopen/coldopen.component";
import { narrations as coldopenNarrations } from "../chapters/coldopen/narrations";
import coldopenLayout from "../chapters/coldopen/layout.json";
import { NotebookRagComponent } from "../chapters/notebook-rag/notebook-rag.component";
import { narrations as notebookRagNarrations } from "../chapters/notebook-rag/narrations";
import notebookRagLayout from "../chapters/notebook-rag/layout.json";
import { RagFailuresComponent } from "../chapters/rag-failures/rag-failures.component";
import { narrations as ragFailuresNarrations } from "../chapters/rag-failures/narrations";
import ragFailuresLayout from "../chapters/rag-failures/layout.json";
import { KgCoreComponent } from "../chapters/kg-core/kg-core.component";
import { narrations as kgCoreNarrations } from "../chapters/kg-core/narrations";
import kgCoreLayout from "../chapters/kg-core/layout.json";
import { KgGovernanceComponent } from "../chapters/kg-governance/kg-governance.component";
import { narrations as kgGovernanceNarrations } from "../chapters/kg-governance/narrations";
import kgGovernanceLayout from "../chapters/kg-governance/layout.json";
import { CompareGraphragComponent } from "../chapters/compare-graphrag/compare-graphrag.component";
import { narrations as compareGraphragNarrations } from "../chapters/compare-graphrag/narrations";
import compareGraphragLayout from "../chapters/compare-graphrag/layout.json";
import { GraphragLimitsComponent } from "../chapters/graphrag-limits/graphrag-limits.component";
import { narrations as graphragLimitsNarrations } from "../chapters/graphrag-limits/narrations";
import graphragLimitsLayout from "../chapters/graphrag-limits/layout.json";
import { SvoProofComponent } from "../chapters/svo-proof/svo-proof.component";
import { narrations as svoProofNarrations } from "../chapters/svo-proof/narrations";
import svoProofLayout from "../chapters/svo-proof/layout.json";
import { ProblemOneCloseComponent } from "../chapters/problem-one-close/problem-one-close.component";
import { narrations as problemOneCloseNarrations } from "../chapters/problem-one-close/narrations";
import problemOneCloseLayout from "../chapters/problem-one-close/layout.json";
import { P2OpenComponent } from "../chapters/p2-open/p2-open.component";
import { narrations as p2OpenNarrations } from "../chapters/p2-open/narrations";
import p2OpenLayout from "../chapters/p2-open/layout.json";
import { P2LiteratureComponent } from "../chapters/p2-literature/p2-literature.component";
import { narrations as p2LiteratureNarrations } from "../chapters/p2-literature/narrations";
import p2LiteratureLayout from "../chapters/p2-literature/layout.json";
import { P2VerificationStackComponent } from "../chapters/p2-verification-stack/p2-verification-stack.component";
import { narrations as p2VerificationStackNarrations } from "../chapters/p2-verification-stack/narrations";
import p2VerificationStackLayout from "../chapters/p2-verification-stack/layout.json";
import { P2DemoCitationComponent } from "../chapters/p2-demo-citation/p2-demo-citation.component";
import { narrations as p2DemoCitationNarrations } from "../chapters/p2-demo-citation/narrations";
import p2DemoCitationLayout from "../chapters/p2-demo-citation/layout.json";
import { P2DemoQaComponent } from "../chapters/p2-demo-qa/p2-demo-qa.component";
import { narrations as p2DemoQaNarrations } from "../chapters/p2-demo-qa/narrations";
import p2DemoQaLayout from "../chapters/p2-demo-qa/layout.json";
import { P2BenchmarkComponent } from "../chapters/p2-benchmark/p2-benchmark.component";
import { narrations as p2BenchmarkNarrations } from "../chapters/p2-benchmark/narrations";
import p2BenchmarkLayout from "../chapters/p2-benchmark/layout.json";
import { P2CloseComponent } from "../chapters/p2-close/p2-close.component";
import { narrations as p2CloseNarrations } from "../chapters/p2-close/narrations";
import p2CloseLayout from "../chapters/p2-close/layout.json";
import { IntroPositioningComponent } from "../chapters/intro-positioning/intro-positioning.component";
import { narrations as introPositioningNarrations } from "../chapters/intro-positioning/narrations";
import introPositioningLayout from "../chapters/intro-positioning/layout.json";
import { IntroBackgroundComponent } from "../chapters/intro-background/intro-background.component";
import { narrations as introBackgroundNarrations } from "../chapters/intro-background/narrations";
import introBackgroundLayout from "../chapters/intro-background/layout.json";
import { IntroGapsComponent } from "../chapters/intro-gaps/intro-gaps.component";
import { narrations as introGapsNarrations } from "../chapters/intro-gaps/narrations";
import introGapsLayout from "../chapters/intro-gaps/layout.json";
import { IntroGoalsComponent } from "../chapters/intro-goals/intro-goals.component";
import { narrations as introGoalsNarrations } from "../chapters/intro-goals/narrations";
import introGoalsLayout from "../chapters/intro-goals/layout.json";
import { IntroRqOverviewComponent } from "../chapters/intro-rq-overview/intro-rq-overview.component";
import { narrations as introRqOverviewNarrations } from "../chapters/intro-rq-overview/narrations";
import introRqOverviewLayout from "../chapters/intro-rq-overview/layout.json";
import { IntroRq1Component } from "../chapters/intro-rq1/intro-rq1.component";
import { narrations as introRq1Narrations } from "../chapters/intro-rq1/narrations";
import introRq1Layout from "../chapters/intro-rq1/layout.json";
import { IntroRq2Component } from "../chapters/intro-rq2/intro-rq2.component";
import { narrations as introRq2Narrations } from "../chapters/intro-rq2/narrations";
import introRq2Layout from "../chapters/intro-rq2/layout.json";
import { IntroRq3Component } from "../chapters/intro-rq3/intro-rq3.component";
import { narrations as introRq3Narrations } from "../chapters/intro-rq3/narrations";
import introRq3Layout from "../chapters/intro-rq3/layout.json";
import { IntroRq4FutureComponent } from "../chapters/intro-rq4-future/intro-rq4-future.component";
import { narrations as introRq4FutureNarrations } from "../chapters/intro-rq4-future/narrations";
import introRq4FutureLayout from "../chapters/intro-rq4-future/layout.json";
import { IntroCarrierStatusComponent } from "../chapters/intro-carrier-status/intro-carrier-status.component";
import { narrations as introCarrierStatusNarrations } from "../chapters/intro-carrier-status/narrations";
import introCarrierStatusLayout from "../chapters/intro-carrier-status/layout.json";

export const CHAPTERS: ChapterDef[] = [
  {
    id: "coldopen",
    title: "開場：為什麼還要知識圖譜",
    narrations: coldopenNarrations,
    layout: coldopenLayout,
    component: ColdopenComponent,
  },
  {
    id: "notebook-rag",
    title: "NotebookLM 到 RAG 核心",
    narrations: notebookRagNarrations,
    layout: notebookRagLayout,
    component: NotebookRagComponent,
  },
  {
    id: "rag-failures",
    title: "2026 RAG 的失敗點",
    narrations: ragFailuresNarrations,
    layout: ragFailuresLayout,
    component: RagFailuresComponent,
  },
  {
    id: "kg-core",
    title: "知識圖譜的核心",
    narrations: kgCoreNarrations,
    layout: kgCoreLayout,
    component: KgCoreComponent,
  },
  {
    id: "kg-governance",
    title: "2026 版 KG 治理",
    narrations: kgGovernanceNarrations,
    layout: kgGovernanceLayout,
    component: KgGovernanceComponent,
  },
  {
    id: "compare-graphrag",
    title: "RAG、KG 與 GraphRAG",
    narrations: compareGraphragNarrations,
    layout: compareGraphragLayout,
    component: CompareGraphragComponent,
  },
  {
    id: "graphrag-limits",
    title: "GraphRAG 的限制",
    narrations: graphragLimitsNarrations,
    layout: graphragLimitsLayout,
    component: GraphragLimitsComponent,
  },
  {
    id: "svo-proof",
    title: "SVO 可信性",
    narrations: svoProofNarrations,
    layout: svoProofLayout,
    component: SvoProofComponent,
  },
  {
    id: "problem-one-close",
    title: "題目一收束",
    narrations: problemOneCloseNarrations,
    layout: problemOneCloseLayout,
    component: ProblemOneCloseComponent,
  },
  {
    id: "p2-open",
    title: "題目二開場",
    narrations: p2OpenNarrations,
    layout: p2OpenLayout,
    component: P2OpenComponent,
  },
  {
    id: "p2-literature",
    title: "三元組驗證的文獻依據",
    narrations: p2LiteratureNarrations,
    layout: p2LiteratureLayout,
    component: P2LiteratureComponent,
  },
  {
    id: "p2-verification-stack",
    title: "三元組驗證閉環",
    narrations: p2VerificationStackNarrations,
    layout: p2VerificationStackLayout,
    component: P2VerificationStackComponent,
  },
  {
    id: "p2-demo-citation",
    title: "Demo 1：來源追溯",
    narrations: p2DemoCitationNarrations,
    layout: p2DemoCitationLayout,
    component: P2DemoCitationComponent,
  },
  {
    id: "p2-demo-qa",
    title: "Demo 2：圖譜問答",
    narrations: p2DemoQaNarrations,
    layout: p2DemoQaLayout,
    component: P2DemoQaComponent,
  },
  {
    id: "p2-benchmark",
    title: "簡化評估成果",
    narrations: p2BenchmarkNarrations,
    layout: p2BenchmarkLayout,
    component: P2BenchmarkComponent,
  },
  {
    id: "p2-close",
    title: "題目二收束",
    narrations: p2CloseNarrations,
    layout: p2CloseLayout,
    component: P2CloseComponent,
  },
  {
    id: "intro-positioning",
    title: "專案介紹：定位與緒論順序",
    narrations: introPositioningNarrations,
    layout: introPositioningLayout,
    component: IntroPositioningComponent,
  },
  {
    id: "intro-background",
    title: "研究背景",
    narrations: introBackgroundNarrations,
    layout: introBackgroundLayout,
    component: IntroBackgroundComponent,
  },
  {
    id: "intro-gaps",
    title: "六個研究缺口",
    narrations: introGapsNarrations,
    layout: introGapsLayout,
    component: IntroGapsComponent,
  },
  {
    id: "intro-goals",
    title: "四個研究目標",
    narrations: introGoalsNarrations,
    layout: introGoalsLayout,
    component: IntroGoalsComponent,
  },
  {
    id: "intro-rq-overview",
    title: "研究問題總覽",
    narrations: introRqOverviewNarrations,
    layout: introRqOverviewLayout,
    component: IntroRqOverviewComponent,
  },
  {
    id: "intro-rq1",
    title: "RQ1：KG-BFS 是否優於強化版 RAG",
    narrations: introRq1Narrations,
    layout: introRq1Layout,
    component: IntroRq1Component,
  },
  {
    id: "intro-rq2",
    title: "RQ2：多知識庫輕量路由",
    narrations: introRq2Narrations,
    layout: introRq2Layout,
    component: IntroRq2Component,
  },
  {
    id: "intro-rq3",
    title: "RQ3：自我精煉降低幻覺",
    narrations: introRq3Narrations,
    layout: introRq3Layout,
    component: IntroRq3Component,
  },
  {
    id: "intro-rq4-future",
    title: "RQ4 簡述與 RQ5/RQ6 未來工作",
    narrations: introRq4FutureNarrations,
    layout: introRq4FutureLayout,
    component: IntroRq4FutureComponent,
  },
  {
    id: "intro-carrier-status",
    title: "研究載體與誠實現況",
    narrations: introCarrierStatusNarrations,
    layout: introCarrierStatusLayout,
    component: IntroCarrierStatusComponent,
  },
];
