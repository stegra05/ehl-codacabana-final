import type { Stage } from "./replay";

export interface Agent {
  id: Stage;
  name: string;
  kind: "Model" | "Code";
  description: string;
  role: string;
  modules: string[];
  inputs: string;
  outputs: string;
}
export const agents: Record<Stage, Agent> = {
  research: {
    id: "research",
    name: "Research team",
    kind: "Model",
    description: "Four specialists. One supplier brief.",
    role: "Economics, persona, history and leverage specialists read the available records. A lead combines their findings into claim order, tone and up to two permitted term trades. Missing data or model failure falls back to the plain engine.",
    modules: ["buyer/research.py", "buyer/personas.py", "buyer/claims.py"],
    inputs: "Supplier records, case facts, prior outcomes",
    outputs: "Checked strategy, evidence and proposed trades",
  },
  rehearsal: {
    id: "rehearsal",
    name: "Argument rehearsal",
    kind: "Model",
    description: "Anticipate objections. Prepare answers.",
    role: "A supplier role raises likely objections and a buyer role prepares evidence-based responses. Code drops lines containing figures. Rehearsal prepares words; the policy retains prices and pace. It runs during research, before the session opens.",
    modules: ["buyer/rehearsal.py", "buyer/research.py"],
    inputs: "Specialist findings and case brief",
    outputs: "Expected arguments, rebuttals and supplier wants",
  },
  analyst: {
    id: "analyst",
    name: "Live analyst",
    kind: "Model",
    description: "Read the reply. Identify the next tactic.",
    role: "Reads opening quotes and subsequent replies. Selects a bounded mood, asks and a steady, hold or argue tactic, and matches rehearsed arguments. Code determines how a tactic affects the next offer. The analyst has a maximum six-second budget and can be skipped when clocks are tight.",
    modules: ["buyer/analyst.py", "buyer/policy.py"],
    inputs: "Latest supplier email and prepared arguments",
    outputs: "Validated tactic, mood, asks and writer notes",
  },
  negotiator: {
    id: "negotiator",
    name: "Decision engine",
    kind: "Code",
    description: "Every price, term and binding decision.",
    role: "The policy tracks each supplier, prices complete packages with arena_kit.total_cost, checks must_haves_ok, selects claims and controls concessions. Proposed trades must pass the cost checks. A model never supplies a binding figure.",
    modules: ["buyer/policy.py", "buyer/economics.py", "buyer/claims.py"],
    inputs: "Standing sheets, supplier state and checked strategy",
    outputs: "Complete term sheets and citable claims",
  },
  writer: {
    id: "writer",
    name: "Email writer",
    kind: "Model",
    description: "Model words. Code-owned figures.",
    role: "An optional model supplies a paragraph. Code assembles the terms, numerical statements and cited claims. Invalid or late model text is replaced by the deterministic template, within the runner's shared reply budget.",
    modules: ["buyer/writer.py", "buyer/llm.py"],
    inputs: "Code-approved proposal, claims and analyst notes",
    outputs: "Supplier email with complete term sheets",
  },
  close: {
    id: "close",
    name: "Close gate",
    kind: "Code",
    description: "Accept the best valid sheet. Or walk.",
    role: "Compares standing supplier sheets at total cost. Accepts the cheapest one that satisfies must-haves and beats the alternative, or walks away. Better alternative sheets must become standing before acceptance. The runner starts closing before the final wave cap.",
    modules: ["buyer/policy.py", "buyer/economics.py", "buyer/runner.py"],
    inputs: "Valid standing supplier offers and the alternative",
    outputs: "One accepted term sheet or a walk-away",
  },
  debrief: {
    id: "debrief",
    name: "Debrief & memory",
    kind: "Model",
    description: "Turn the outcome into the next input.",
    role: "When a score is available, saves the outcome and a short lesson. Later research recalls comparable runs by case and supplier features, using their observed price paths and scores. A single lesson is not treated as a rule. Final waves disable debrief recording.",
    modules: ["buyer/memory.py", "buyer/runner.py"],
    inputs: "Case outcome, price paths and supplier reasons",
    outputs: "Observed results for later research",
  },
};
export const lanes: { name: string; label: string; ids: Stage[] }[] = [
  {
    name: "Prepare",
    label: "Before the session opens",
    ids: ["research", "rehearsal"],
  },
  {
    name: "Negotiate",
    label: "Repeat for each supplier reply",
    ids: ["analyst", "negotiator", "writer"],
  },
  {
    name: "Close & learn",
    label: "One outcome, a reusable record",
    ids: ["close", "debrief"],
  },
];
