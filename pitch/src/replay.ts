// The recorded session (`pitch/export.py` writes replay.json) and what the monitor shows at each
// point of the replay. Events are replayed by round, not by wall clock: in an RFQ the threads
// interleave, and "our e-mails, then their replies" reads better than the exact order.
import raw from "./replay.json";

export type Sid = string;
export type Mood = "open" | "firm" | "closing";
export interface Terms {
  unit_price?: number;
  payment_days?: number;
  lead_time_days?: number;
}

export interface Supplier {
  id: Sid;
  name: string;
  short: string;
  owner: string | null;
  signals: string[];
  quote: Terms;
  std: Terms;
  anchor: number;
  quote_at_terms: number;
  budget: number;
}

export interface Playbook {
  floor: number;
  first_drop: number;
  step: number;
  counters: number;
  patience: number;
  eager: boolean;
}

export interface Run {
  anchor: number;
  fraction: number;
  ours: number[];
  theirs: number[];
  price: number;
  end: "agreed" | "final_offer" | "round_limit";
}

export interface Research {
  findings: Record<string, string[]>;
  strategy: {
    shift: number;
    fraction: number;
    claim_order: string[];
    tone: string | null;
    notes: string;
    reason: string;
  };
  playbook: Playbook | null;
  rehearsal: { default: number; anchor: number; fraction: number; runs: Run[] } | null;
  opening: number;
}

type At<K extends string, T> = { t: number; kind: K } & T;
export type Ev =
  | At<"research", { until: number }>
  | At<"open", { quotes: Record<Sid, Terms>; standing: Record<Sid, number | null> }>
  | At<"analyst", { supplier: Sid; seconds: number; mood: Mood; asks: string[]; notes: string }>
  | At<
      "send",
      {
        supplier: Sid;
        round: number;
        price: number;
        terms: Terms;
        claims: string[];
        refs: string[];
        body: string;
        model_paragraph: boolean;
        theirs: number;
        rule: "anchor" | "hold" | "step";
        conceded: number | null;
      }
    >
  | At<
      "reply",
      {
        supplier: Sid;
        round: number;
        status: string;
        price: number;
        terms: Terms;
        checks: string[];
        text: string;
        reasons: string[];
        standing: Record<Sid, number | null>;
      }
    >
  | At<"keepalive", { supplier: Sid; round: number }>
  | At<"accept", { supplier: Sid; price: number }>
  | At<"debrief", object>;

export interface Replay {
  case: {
    id: string;
    title: string;
    type: string;
    goal: string;
    need_per_year: number;
    horizon_years: number;
    current_price: number;
    must_haves: { field: string; op: string; value: number }[];
  };
  session: { id: string; set: string; recorded: string; end: number };
  calls: { research: number; roleplay: number; analyst: number; writer: number; debrief: number };
  suppliers: Supplier[];
  research: Record<Sid, Research>;
  events: Ev[];
  close: {
    t: number;
    supplier: Sid;
    terms: Terms;
    c_open: number;
    c_deal: number;
    c_best: number;
    score: number;
    standing: Record<Sid, number | null>;
  };
  lesson: {
    goal: string;
    type: string;
    bidders: number;
    owners: string[];
    signals: string[];
    score: number;
    threads: { opened: number; fraction: number; ours: number[]; theirs: number[] }[];
    lesson: string;
  };
}

export const replay = raw as unknown as Replay;
export const suppliers = replay.suppliers;
export const byId = Object.fromEntries(suppliers.map((s) => [s.id, s]));

// The order the replay walks: research (0), the quotes (1), the rehearsal in setup (1.5), then
// per round our e-mails (2r) and its replies (2r + 1), the accept (8), the debrief (9). The live
// analyst reads a supplier's e-mail just before our next one to it, so it joins that reply.
function beatOf(e: Ev, i: number): number {
  switch (e.kind) {
    case "research":
      return 0;
    case "open":
      return 1;
    case "analyst": {
      const read = replay.events
        .slice(0, i)
        .reverse()
        .find((x) => x.kind === "reply" && x.supplier === e.supplier);
      return read && read.kind === "reply" ? 2 * read.round + 1 : 1;
    }
    case "send":
    case "keepalive":
      return 2 * e.round;
    case "reply":
      return 2 * e.round + 1;
    case "accept":
      return 8;
    case "debrief":
      return 9;
  }
}
const beats = replay.events.map(beatOf);
export const REHEARSED = 1.5;

export type Status = "waiting" | "quoted" | "countered" | "agreed" | "accepted";
export interface Thread {
  supplier: Supplier;
  status: Status;
  quote: number | null;
  ours: number[];
  theirs: number[];
  standing: number | null; // total cost of its standing sheet; null: breaks a must-have
  lead: number | null;
}

export interface Snapshot {
  cut: number;
  t: number;
  events: Ev[];
  threads: Thread[];
  best: number | null;
  sent: number;
  modelParagraphs: number;
  reads: number;
  cited: number;
  verified: number;
  round: number;
  accepted: boolean;
  debriefed: boolean;
}

export function snapshot(cut: number): Snapshot {
  const events = replay.events.filter((_, i) => beats[i] <= cut);
  const t = events.reduce((m, e) => Math.max(m, e.kind === "research" ? e.until : (e.t ?? 0)), 0);
  let standing: Record<Sid, number | null> = {};
  for (const e of events) if (e.kind === "open" || e.kind === "reply") standing = e.standing;
  const accepted = events.some((e) => e.kind === "accept");
  const threads = suppliers.map((s): Thread => {
    const mine = events.filter((e) => "supplier" in e && e.supplier === s.id);
    const replies = mine.flatMap((e) => (e.kind === "reply" ? [e] : []));
    const opened = events.some((e) => e.kind === "open");
    const last = replies.at(-1);
    let status: Status = opened ? "quoted" : "waiting";
    if (last) status = last.status === "agreed" || replies.some((r) => r.status === "agreed") ? "agreed" : "countered";
    if (accepted && replay.close.supplier === s.id) status = "accepted";
    const terms = last?.terms ?? s.quote;
    return {
      supplier: s,
      status,
      quote: opened ? (s.quote.unit_price ?? null) : null,
      ours: mine.flatMap((e) => (e.kind === "send" ? [e.price] : [])),
      theirs: [...(opened && s.quote.unit_price ? [s.quote.unit_price] : []), ...replies.map((r) => r.price)],
      standing: standing[s.id] ?? null,
      lead: opened ? (terms.lead_time_days ?? s.std.lead_time_days ?? null) : null,
    };
  });
  const costs = Object.values(standing).filter((c): c is number => c !== null);
  const sends = events.flatMap((e) => (e.kind === "send" ? [e] : []));
  const checks = events.flatMap((e) => (e.kind === "reply" ? e.checks : []));
  return {
    cut,
    t,
    events,
    threads,
    best: costs.length ? Math.min(...costs) : null,
    sent: sends.length,
    modelParagraphs: sends.filter((e) => e.model_paragraph).length,
    reads: events.filter((e) => e.kind === "analyst").length,
    cited: sends.reduce((n, e) => n + e.claims.length, 0),
    verified: checks.filter((c) => c === "verified").length,
    round: sends.reduce((r, e) => Math.max(r, e.round), 0),
    accepted,
    debriefed: events.some((e) => e.kind === "debrief"),
  };
}

const eur0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR", minimumFractionDigits: 2 });
export const money = (v: number) => eur0.format(v);
export const price = (v: number) => eur2.format(v);
export const pct = (v: number, digits = 1) => `${v < 0 ? "\u2212" : ""}${Math.abs(v * 100).toFixed(digits)}%`;
export const clock = (s: number) =>
  `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export const AGENTS = replay.calls.research + replay.calls.roleplay + 3; // + analyst, writer, debrief

export const MAX_LEAD = replay.case.must_haves.find((m) => m.field === "lead_time_days" && m.op === "<=")?.value;
export const leadBreach = (lead: number | null | undefined) => MAX_LEAD !== undefined && lead != null && lead > MAX_LEAD;
export const breaks = (s: Supplier) => leadBreach(s.quote.lead_time_days ?? s.std.lead_time_days);
