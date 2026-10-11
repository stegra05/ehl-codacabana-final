// The replay's steps: what changes with each click, where to look (one focus) and the headline.
// Every figure in a headline comes from the recorded session.
import { breaks, byId, pct, price, REHEARSED, replay, type Sid, suppliers } from "./replay";

export type Focus = "team" | "records" | "research" | "rehearsal" | "negotiator" | "analyst" | "writer" | "debrief" | "suppliers";
export type View =
  | "case"
  | "research"
  | "quotes"
  | "rehearsal"
  | "emails"
  | "replies"
  | "decisions"
  | "agreed"
  | "close"
  | "debrief"
  | "final";
export type Phase = "Prepare" | "Negotiate" | "Close" | "Learn";

export interface Step {
  key: string;
  label: string;
  phase: Phase;
  cut: number;
  focus: Focus;
  view: View;
  edges: string[];
  headline: string;
  supplier?: Sid; // the supplier a view opens on
}

const ev = replay.events;
const sends = (round: number) => ev.flatMap((e) => (e.kind === "send" && e.round === round ? [e] : []));
const replies = (round: number) => ev.flatMap((e) => (e.kind === "reply" && e.round === round ? [e] : []));
const winner = byId[replay.close.supplier];

const broken = suppliers.filter(breaks);
const quotesLine =
  `${suppliers.length} quotes in` +
  (broken.length
    ? `. ${broken.map((s) => `${s.short}'s ${s.quote.lead_time_days} days`).join(", ")} ${broken.length > 1 ? "break" : "breaks"} our must-have`
    : "");

// the supplier whose opening the rehearsal moved, else the winner
const tuned = suppliers.find((s) => {
  const r = replay.research[s.id]?.rehearsal;
  return r && r.anchor !== r.default;
});
const rehearsalLine = (() => {
  if (!tuned) return "Every rehearsal keeps our usual opening";
  const r = replay.research[tuned.id].rehearsal!;
  return `Opening at ${pct(r.default, 0)} would end the talks. ${tuned.short} gets ${pct(r.anchor, 0)}`;
})();

const round1 = sends(1);
const facts1 = round1.reduce((n, e) => n + e.claims.length, 0);
const replies1 = replies(1);
const verified1 = replies1.reduce((n, e) => n + e.checks.filter((c) => c === "verified").length, 0);
const biggest = replies1
  .map((r) => ({ r, drop: 1 - r.price / (byId[r.supplier].quote.unit_price ?? r.price) }))
  .sort((a, b) => b.drop - a.drop)[0];

const held = sends(2).filter((e) => e.rule === "hold");
const minHold = Math.min(...held.map((e) => e.conceded ?? 0));

const agreedCount = ev.filter((e) => e.kind === "reply" && e.status === "agreed").length;

export const steps: Step[] = [
  {
    key: "case",
    label: "Case",
    phase: "Prepare",
    cut: -1,
    focus: "team",
    view: "case",
    edges: [],
    headline: "One case, one purchasing team",
  },
  {
    key: "research",
    label: "Research",
    phase: "Prepare",
    cut: 0,
    focus: "research",
    view: "research",
    edges: ["records-research"],
    headline: "Four specialists read our records on each supplier",
    supplier: winner.id,
  },
  {
    key: "quotes",
    label: "Quotes",
    phase: "Prepare",
    cut: 1,
    focus: "analyst",
    view: "quotes",
    edges: ["suppliers-analyst"],
    headline: quotesLine,
  },
  {
    key: "rehearsal",
    label: "Rehearsal",
    phase: "Prepare",
    cut: REHEARSED,
    focus: "rehearsal",
    view: "rehearsal",
    edges: ["rehearsal-negotiator"],
    headline: rehearsalLine,
    supplier: (tuned ?? winner).id,
  },
  {
    key: "round1",
    label: "Round 1",
    phase: "Negotiate",
    cut: 2,
    focus: "writer",
    view: "emails",
    edges: ["writer-suppliers"],
    headline: `${round1.length} e-mails, ${facts1} facts cited, every figure from code`,
    supplier: round1.find((e) => e.model_paragraph)?.supplier ?? winner.id,
  },
  {
    key: "replies",
    label: "Replies",
    phase: "Negotiate",
    cut: 3,
    focus: "analyst",
    view: "replies",
    edges: ["suppliers-analyst"],
    headline: `${verified1 === facts1 ? `All ${facts1}` : `${verified1} of ${facts1}`} facts verified. ${byId[biggest.r.supplier].short} drops ${pct(biggest.drop)}`,
  },
  {
    key: "round2",
    label: "Round 2",
    phase: "Negotiate",
    cut: 4,
    focus: "negotiator",
    view: "decisions",
    edges: ["negotiator-writer"],
    headline:
      held.length > 0
        ? `${held.length === 1 ? byId[held[0].supplier].short : `${held.length} suppliers`} dropped ${pct(minHold, 0)} or more at once. We hold our price`
        : "Every supplier moved a little. We move a share of the gap",
  },
  {
    key: "agreed",
    label: "Agreed",
    phase: "Negotiate",
    cut: 7,
    focus: "suppliers",
    view: "agreed",
    edges: [],
    headline: `${agreedCount === suppliers.length ? `All ${agreedCount}` : agreedCount} agree. ${winner.short} at ${price(replay.close.terms.unit_price ?? 0)}`,
  },
  {
    key: "close",
    label: "Close",
    phase: "Close",
    cut: 8,
    focus: "negotiator",
    view: "close",
    edges: [],
    headline: `Accept ${winner.short}: lowest total cost, every must-have kept`,
  },
  {
    key: "debrief",
    label: "Debrief",
    phase: "Learn",
    cut: 9,
    focus: "debrief",
    view: "debrief",
    edges: ["negotiator-debrief", "debrief-research"],
    headline: "One lesson for the next case like this",
  },
  {
    key: "final",
    label: "Live Final",
    phase: "Learn",
    cut: 9,
    focus: "team",
    view: "final",
    edges: [],
    headline: "In the Live Final, every case gets its own team",
  },
];

// what a click on a node shows, at the current point of the replay
export const nodeView: Record<Focus, View> = {
  team: "case",
  records: "research",
  research: "research",
  rehearsal: "rehearsal",
  negotiator: "decisions",
  analyst: "replies",
  writer: "emails",
  debrief: "debrief",
  suppliers: "agreed",
};
