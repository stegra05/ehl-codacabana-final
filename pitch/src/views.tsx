// What the inspector shows for each view, at the current point of the replay.
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { byId, leadBreach, money, pct, price, replay, type Run, type Sid, type Snapshot, suppliers } from "./replay";
import type { View } from "./steps";

const GROUPS: [string, string][] = [
  ["economics", "Economics"],
  ["persona", "Persona"],
  ["history", "History"],
  ["leverage", "Leverage"],
];
const KINDS: Record<string, string> = {
  should_cost: "should-cost",
  order_history: "order history",
  index: "cost indices",
  notice: "notice period",
  rival: "rival offers",
  forecast: "forecast",
  scorecard: "scorecard",
  hedged: "hedging",
};
const winner = byId[replay.close.supplier];

export function eyebrow(view: View, snap: Snapshot): string {
  const c = replay.calls;
  switch (view) {
    case "case":
      return `Case ${replay.case.id} · ${replay.case.type.toUpperCase()} · goal ${replay.case.goal}`;
    case "research":
      return `Research team · ${c.research - suppliers.length} specialists, ${suppliers.length} leads · before the first e-mail`;
    case "quotes":
    case "replies":
      return `Live analyst · reads every supplier e-mail · ${snap.reads} reads`;
    case "rehearsal":
      return `Rehearsal · ${c.roleplay} role-played suppliers · demo bids in code`;
    case "emails":
      return `Writer · a model writes the words, code writes every figure`;
    case "decisions":
      return "Negotiator · code · sets every price";
    case "agreed":
      return "Suppliers · their words";
    case "close":
      return "Negotiator · close gate · code";
    case "debrief":
      return "Debrief · one agent · after the case";
    case "final":
      return "Live Final · five waves · eight minutes each · up to 10 cases at once";
  }
}

// which views have a supplier to choose
export const TABBED: View[] = ["research", "rehearsal", "emails"];

export function Body({ view, snap, sid }: { view: View; snap: Snapshot; sid: Sid }): ReactNode {
  switch (view) {
    case "case":
      return <CaseView />;
    case "research":
      return <ResearchView sid={sid} />;
    case "quotes":
      return <QuotesView snap={snap} />;
    case "rehearsal":
      return <RehearsalView sid={sid} />;
    case "emails":
      return <EmailView snap={snap} sid={sid} />;
    case "replies":
      return <RepliesView snap={snap} />;
    case "decisions":
      return <DecisionsView snap={snap} />;
    case "agreed":
      return <AgreedView snap={snap} />;
    case "close":
      return <CloseView />;
    case "debrief":
      return <DebriefView />;
    case "final":
      return <FinalView />;
  }
}

// ------------------------------------------------------------------ prepare

function CaseView() {
  const k = replay.case;
  const must = k.must_haves.map((m) => `${m.field.replaceAll("_", " ").replace(" days", "")} ${m.op.replace("<=", "≤").replace(">=", "≥")} ${m.value} days`);
  const roster: [string, "model" | "code", string, string][] = [
    ["Research team", "model", `${replay.calls.research}`, "four specialists and a lead per supplier"],
    ["Rehearsal", "model", `${replay.calls.roleplay}`, "role-play each supplier; code plays demo bids"],
    ["Live analyst", "model", "1", "reads every supplier e-mail"],
    ["Writer", "model", "1", "writes the words around code's figures"],
    ["Debrief", "model", "1", "turns the outcome into a lesson"],
    ["Negotiator", "code", "", "sets every price, term and accept"],
  ];
  return (
    <div className="view">
      <div className="col">
        <dl className="kv">
          <dt>Buy</dt>
          <dd>{`${k.need_per_year.toLocaleString("en-US")} pump shafts a year, ${k.horizon_years * 12} months`}</dd>
          <dt>Today</dt>
          <dd>{`${price(k.current_price)} a unit`}</dd>
          <dt>Must-have</dt>
          <dd>{must.join(", ")}</dd>
          <dt>Suppliers</dt>
          <dd>{suppliers.map((s) => s.short).join(", ")}</dd>
          <dt>Score</dt>
          <dd>total cost over the term, not the price alone</dd>
        </dl>
      </div>
      <div className="col">
        <div className="rows">
          {roster.map(([name, kind, n, what]) => (
            <div key={name} className="row" style={{ gridTemplateColumns: "34px 210px 70px 1fr", padding: "6px 0" }}>
              <Shape kind={kind} />
              <span className="who">{name}</span>
              <span className="mono" style={{ fontSize: 18 }}>
                {kind === "model" ? `×${n}` : "code"}
              </span>
              <span className="quiet">{what}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Shape({ kind, size = 18 }: { kind: "model" | "code"; size?: number }) {
  const r = size / 2 - 1.5;
  const c = size / 2;
  return (
    <svg width={size} height={size} style={{ alignSelf: "center" }}>
      {kind === "model" ? (
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--ink)" strokeWidth={1.5} />
      ) : (
        <polygon
          points={Array.from({ length: 6 }, (_, i) => `${c + r * Math.cos((Math.PI / 3) * i)},${c + r * Math.sin((Math.PI / 3) * i)}`).join(" ")}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={1.5}
        />
      )}
    </svg>
  );
}

function ResearchView({ sid }: { sid: Sid }) {
  const r = replay.research[sid];
  const s = r.strategy;
  const opening = r.opening;
  return (
    <div className="view">
      <div className="col">
        <div className="eyebrow" style={{ marginBottom: 12 }}>
          The lead's strategy for {byId[sid].short}
        </div>
        <dl className="kv">
          <dt>Open at</dt>
          <dd>
            <span className="mono">{pct(opening, 0)}</span> of its quote
            {s.shift > 0 ? <span className="quiet">{` (asked +${pct(s.shift, 0)})`}</span> : null}
          </dd>
          <dt>Pace</dt>
          <dd>
            <span className="mono">{pct(s.fraction, 0)}</span> of the gap a round
          </dd>
          <dt>Lead with</dt>
          <dd>{s.claim_order.slice(0, 3).map((k) => KINDS[k] ?? k).join(", ")}</dd>
          <dt>Tone</dt>
          <dd>{s.tone ?? "usual"}</dd>
        </dl>
        <p className="quiet clamp2" style={{ fontSize: 17, lineHeight: 1.4, margin: "12px 0 0" }}>
          {s.reason}
        </p>
      </div>
      <div className="col grid2">
        {GROUPS.map(([key, name]) => (
          <div key={key} className="finding">
            <div className="eyebrow">{`${name} specialist`}</div>
            <p>{r.findings[key]?.[0] ?? "Nothing in our records."}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function QuotesView({ snap }: { snap: Snapshot }) {
  const reads = snap.events.flatMap((e) => (e.kind === "analyst" ? [e] : []));
  return (
    <div className="view">
      <div className="col">
        <div className="rows">
          <div className="row th" style={{ gridTemplateColumns: "1fr 110px 120px" }}>
            <span>Supplier</span>
            <span style={{ textAlign: "right" }}>Price</span>
            <span style={{ textAlign: "right" }}>Lead time</span>
          </div>
          {snap.threads.map((th) => {
            const lead = th.supplier.quote.lead_time_days ?? th.supplier.std.lead_time_days;
            const bad = leadBreach(lead);
            return (
              <div key={th.supplier.id} className="row" style={{ gridTemplateColumns: "1fr 110px 120px" }}>
                <span className="who">{th.supplier.name}</span>
                <span className="num">{price(th.quote ?? 0)}</span>
                <span className="num" style={bad ? { fontWeight: 700 } : undefined}>
                  {lead !== undefined ? `${lead} d${bad ? " ✕" : ""}` : "-"}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="col">
        <Readings reads={reads} />
      </div>
    </div>
  );
}

function Readings({ reads }: { reads: { supplier: Sid; mood: string; notes: string; seconds: number }[] }) {
  const missing = suppliers.filter((s) => !reads.some((r) => r.supplier === s.id));
  return (
    <div>
      {suppliers.flatMap((s) => reads.filter((r) => r.supplier === s.id).slice(-1)).map((r, i) => (
        <div key={i} className="reading">
          <div>
            <div className="who">{byId[r.supplier].short}</div>
            <span className={`mood ${r.mood}`}>{r.mood}</span>
            <span className="mono quiet" style={{ fontSize: 13, marginLeft: 8 }}>{`${r.seconds.toFixed(1)} s`}</span>
          </div>
          <p>{r.notes}</p>
        </div>
      ))}
      {missing.length > 0 && (
        <p className="quiet" style={{ fontSize: 16, margin: "10px 0 0" }}>
          {`${missing.map((s) => s.short).join(", ")}: no reading. Under 2 s left on its clock, the e-mail went out without one.`}
        </p>
      )}
    </div>
  );
}

function RehearsalView({ sid }: { sid: Sid }) {
  const r = replay.research[sid];
  const reh = r.rehearsal;
  const pb = r.playbook;
  const s = byId[sid];
  const openings = reh ? [...new Set(reh.runs.map((x) => x.anchor))] : [];
  return (
    <div className="view">
      <div className="col">
        <div className="eyebrow" style={{ marginBottom: 12 }}>
          {`${s.short}, as three role-plays agree it bids`}
        </div>
        {pb ? (
          <dl className="kv">
            <dt>Lowest price</dt>
            <dd>
              <span className="mono">{pct(pb.floor)}</span> of its quote
            </dd>
            <dt>Steps</dt>
            <dd>
              <span className="mono">{pct(pb.first_drop)}</span>, then at most <span className="mono">{pct(pb.step)}</span>
            </dd>
            <dt>Counters</dt>
            <dd>
              <span className="mono">{pb.counters}</span> before its final offer
            </dd>
            <dt>Patience</dt>
            <dd>
              a gap of <span className="mono">{Math.round(pb.patience * 100)}</span> points to its quote
            </dd>
          </dl>
        ) : null}
        <p className="quiet clamp2" style={{ fontSize: 17, lineHeight: 1.4, margin: "12px 0 0" }}>
          {reh
            ? `Code bid ${reh.runs.length} times against it, ${openings.length} openings at ${new Set(reh.runs.map((x) => x.fraction)).size} paces, in milliseconds. Only the opening may move, by up to 2 points.`
            : `${s.short} is fully booked, so its opening is fixed at ${pct(r.opening, 0)} of the quote. Nothing to rehearse.`}
        </p>
      </div>
      <div className="col">{reh && pb ? <Lanes reh={reh} patience={pb.patience} /> : <Empty text="No demo bids for this supplier." />}</div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="quiet" style={{ fontSize: 19, margin: 0 }}>{text}</p>;
}

// the demo bids, one lane per opening: our opening, its quote, and its patience as a bracket;
// an opening deeper than its patience ends the talks at once
function Lanes({ reh, patience }: { reh: { default: number; anchor: number; fraction: number; runs: Run[] }; patience: number }) {
  const W = 960;
  const L = 150;
  const R = 250;
  const lo = 0.74;
  const x = (v: number) => L + ((v - lo) / (1 - lo)) * (W - L - R);
  const openings = [...new Set(reh.runs.map((r) => r.anchor))].sort((a, b) => a - b);
  const top = 62;
  const lane = 52;
  const edge = Math.max(lo, 1 - patience);
  return (
    <svg className="chart" width={W} height={top + openings.length * lane}>
      <line x1={x(edge)} x2={x(1)} y1={30} y2={30} stroke="var(--ink-2)" strokeWidth={1.5} />
      <line x1={x(edge)} x2={x(edge)} y1={23} y2={37} stroke="var(--ink-2)" strokeWidth={1.5} />
      <line x1={x(1)} x2={x(1)} y1={23} y2={37} stroke="var(--ink-2)" strokeWidth={1.5} />
      <text x={(x(edge) + x(1)) / 2} y={14} textAnchor="middle">
        {`its patience: ${Math.round(patience * 100)} points`}
      </text>
      <line className="grid" x1={x(edge)} x2={x(edge)} y1={37} y2={top + openings.length * lane - 8} strokeDasharray="3 4" />
      {openings.map((a, i) => {
        const runs = reh.runs.filter((r) => r.anchor === a);
        const chosen = a === reh.anchor;
        const ends = runs.every((r) => r.theirs.length === 1 && r.end !== "agreed");
        const y = top + i * lane + lane / 2 - 6;
        const color = chosen ? "var(--signal)" : "var(--ink-2)";
        return (
          <g key={a}>
            <text className="label" x={0} y={y} dy="0.35em" style={{ fontWeight: chosen ? 600 : 400 }}>
              {`open at ${pct(a, 0)}`}
            </text>
            <line x1={x(lo)} x2={x(1)} y1={y} y2={y} stroke="var(--rule)" strokeWidth={1} />
            <motion.rect
              y={y - 5}
              height={10}
              rx={5}
              fill={chosen ? "var(--signal-wash)" : "var(--wash)"}
              initial={{ x: x(1), width: 0 }}
              animate={{ x: x(a), width: x(1) - x(a) }}
              transition={{ duration: 0.7, delay: 0.15 + i * 0.12, ease: [0.2, 0.7, 0.2, 1] }}
            />
            <circle cx={x(1)} cy={y} r={7} fill="var(--sheet)" stroke="var(--ink)" strokeWidth={2} />
            <motion.circle
              cy={y}
              r={7}
              fill={color}
              stroke="var(--sheet)"
              strokeWidth={2}
              initial={{ cx: x(1) }}
              animate={{ cx: x(a) }}
              transition={{ duration: 0.7, delay: 0.15 + i * 0.12, ease: [0.2, 0.7, 0.2, 1] }}
            />
            <text className="label" x={W - R + 28} y={y} dy="0.35em" style={{ fill: chosen ? "var(--ink)" : "var(--ink-2)", fontWeight: chosen ? 600 : 400 }}>
              {ends ? "ends the talks at once" : chosen ? "keeps talking: chosen" : "keeps talking"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ------------------------------------------------------------------ negotiate

const ID = /\(((?:idx|sc|cost|offer|po|fc|doc|ctr|qn|news|quote):[^)]+)\)/;
const FIGURE = /(EUR\s?[\d.,]+|-?\d+(?:\.\d+)?%)/g;

function figures(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(FIGURE)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    out.push(
      <span key={m.index} className="fig">
        {m[0]}
      </span>,
    );
    last = m.index! + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

function EmailView({ snap, sid }: { snap: Snapshot; sid: Sid }) {
  const mine = snap.events.flatMap((e) => (e.kind === "send" && e.supplier === sid ? [e] : []));
  const mail = mine.at(-1) ?? replay.events.flatMap((e) => (e.kind === "send" && e.supplier === sid ? [e] : []))[0];
  if (!mail || mail.kind !== "send") return <Empty text="No e-mail to this supplier yet." />;
  const lines = mail.body
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !/^(Dear|Kind regards|Hollerau Pumpenwerke, Purchasing|Thank you for your offer and for the time|Thank you for your reply|We confirm a binding)/.test(l));
  const sent = snap.events.flatMap((e) => (e.kind === "send" ? [e] : []));
  return (
    <div className="view">
      <div className="col">
        <dl className="kv">
          <dt>E-mails</dt>
          <dd>
            <span className="mono">{sent.length}</span> sent, <span className="mono">{sent.filter((e) => e.model_paragraph).length}</span> with a model paragraph
          </dd>
          <dt>Facts</dt>
          <dd>
            <span className="mono">{sent.reduce((n, e) => n + e.claims.length, 0)}</span> cited, each with its data ID
          </dd>
          <dt>Guard</dt>
          <dd>a paragraph with a digit, an ID or a leak is dropped</dd>
          <dt>Late</dt>
          <dd>under 2 s on the clock: the template goes out</dd>
        </dl>
        <div className="key" style={{ marginTop: 16 }}>
          <span>
            <Shape kind="model" size={16} /> written by a model
          </span>
          <span>
            <Shape kind="code" size={16} /> written by code
          </span>
        </div>
      </div>
      <div className="col mail">
        <div className="eyebrow" style={{ marginBottom: 2 }}>{`Round ${mail.round} · to ${byId[sid].name}`}</div>
        {lines.map((l, i) => {
          const id = l.match(ID);
          const model = mail.model_paragraph && !/\d/.test(l) && i === 0;
          const text = id ? l.replace(ID, "").replace(/\s+\./, ".").trim() : l;
          return (
            <div key={i} className={`mail-line ${model ? "model" : "code"}`}>
              <Shape kind={model ? "model" : "code"} size={16} />
              <p className={model ? "clamp2" : undefined}>
                {model ? text : figures(text)}
                {id ? <span className="ref">{id[1].split(", ")[0] + (id[1].includes(", ") ? " +1" : "")}</span> : null}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RepliesView({ snap }: { snap: Snapshot }) {
  const reads = snap.events.flatMap((e) => (e.kind === "analyst" ? [e] : []));
  const latest = suppliers.map((s) => {
    const rs = snap.events.flatMap((e) => (e.kind === "reply" && e.supplier === s.id ? [e] : []));
    return { s, r: rs.at(-1), before: rs.at(-2)?.price ?? s.quote.unit_price ?? 0 };
  });
  return (
    <div className="view">
      <div className="col">
        <div className="rows">
          <div className="row th" style={{ gridTemplateColumns: "1fr 100px 100px 90px" }}>
            <span>Supplier</span>
            <span style={{ textAlign: "right" }}>Now</span>
            <span style={{ textAlign: "right" }}>Change</span>
            <span style={{ textAlign: "right" }}>Facts</span>
          </div>
          {latest.map(({ s, r, before }) => (
            <div key={s.id} className="row" style={{ gridTemplateColumns: "1fr 100px 100px 90px" }}>
              <span className="who">{s.short}</span>
              <span className="num">{r ? price(r.price) : "-"}</span>
              <span className="num">{r ? pct(r.price / before - 1) : "-"}</span>
              <span className="num">{r ? `${r.checks.filter((c) => c === "verified").length}/${r.checks.length} ✓` : "-"}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="col">
        <Readings reads={reads} />
      </div>
    </div>
  );
}

const RULE: Record<string, (conceded: number | null) => string> = {
  anchor: () => "open at the anchor",
  hold: (c) => `it dropped ${pct(c ?? 0)} at once: room left, hold our price`,
  step: (c) => (c ? `it moved ${pct(c)}: move ${pct(0.3, 0)} of the gap` : "it held: a small step"),
};

function DecisionsView({ snap }: { snap: Snapshot }) {
  const round = Math.max(1, snap.round);
  const rows = snap.events.flatMap((e) => (e.kind === "send" && e.round === round ? [e] : []));
  return (
    <div className="view">
      <div className="col">
        <p className="lede">
          No model sets a number. Each price comes from the same rules for every supplier: open at an anchor set by the case goal, move a share of the gap each round, and hold after a deep first drop, because a supplier that gives that much has more to give.
        </p>
      </div>
      <div className="col">
        <div className="rows">
          <div className="row th" style={{ gridTemplateColumns: "150px 110px 110px 1fr" }}>
            <span>{`Round ${round}`}</span>
            <span style={{ textAlign: "right" }}>Its price</span>
            <span style={{ textAlign: "right" }}>Ours</span>
            <span>Why</span>
          </div>
          {rows.map((e) => (
            <div key={e.supplier} className={`row ${e.rule === "hold" ? "pick" : ""}`} style={{ gridTemplateColumns: "150px 110px 110px 1fr" }}>
              <span className="who">{byId[e.supplier].short}</span>
              <span className="num">{price(e.theirs)}</span>
              <span className="num">{price(e.price)}</span>
              <span className="quiet" style={{ fontSize: 18 }}>
                {RULE[e.rule](e.conceded)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const AGREEING = [/good price/i, /accept this/i, /let's get this/i, /lock in/i, /we can do that/i, /keep making/i];

// the sentence of its e-mail that says yes, as it wrote it
function yes(text: string) {
  const sentences = text.split(/\n|(?<=[.!?])\s+/).map((x) => x.trim()).filter(Boolean);
  for (const re of AGREEING) {
    const hit = sentences.find((x) => re.test(x));
    if (hit) return hit;
  }
  return sentences[1] ?? "";
}

function AgreedView({ snap }: { snap: Snapshot }) {
  const agreed = suppliers.map((s) => {
    const r = snap.events.flatMap((e) => (e.kind === "reply" && e.supplier === s.id && e.status === "agreed" ? [e] : []))[0];
    return { s, r };
  });
  return (
    <div className="view">
      <div className="col">
        <div className="rows">
          <div className="row th" style={{ gridTemplateColumns: "1fr 110px 110px 90px" }}>
            <span>Supplier</span>
            <span style={{ textAlign: "right" }}>Quote</span>
            <span style={{ textAlign: "right" }}>Agreed</span>
            <span style={{ textAlign: "right" }}>Round</span>
          </div>
          {agreed.map(({ s, r }) => (
            <div key={s.id} className="row" style={{ gridTemplateColumns: "1fr 110px 110px 90px" }}>
              <span className="who">{s.short}</span>
              <span className="num quiet">{price(s.quote.unit_price ?? 0)}</span>
              <span className="num">{r ? price(r.price) : "open"}</span>
              <span className="num">{r ? r.round : ""}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="col">
        {agreed
          .filter((a) => a.r)
          .map(({ s, r }) => (
            <div key={s.id} className="reading" style={{ gridTemplateColumns: "140px 1fr" }}>
              <div className="who">{s.short}</div>
              <p>{`\u201C${yes(r!.text)}\u201D`}</p>
            </div>
          ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ close and learn

function CloseView() {
  const c = replay.close;
  const saved = 1 - c.c_deal / c.c_open;
  const rows = suppliers
    .map((s) => ({ s, cost: c.standing[s.id] }))
    .sort((a, b) => (a.cost ?? Infinity) - (b.cost ?? Infinity));
  return (
    <div className="view">
      <div className="col">
        <div className="eyebrow">Total cost of the deal</div>
        <div className="hero" style={{ marginTop: 6 }}>
          {money(c.c_deal)}
        </div>
        <div className="hero-sub">
          {`${pct(saved)} below the opening offers (${money(c.c_open)}). That is ${pct(c.score, 0)} of the best saving possible in this case.`}
        </div>
      </div>
      <div className="col">
        <div className="rows">
          <div className="row th" style={{ gridTemplateColumns: "1fr 110px 120px 160px" }}>
            <span>Standing offer</span>
            <span style={{ textAlign: "right" }}>Price</span>
            <span style={{ textAlign: "right" }}>Must-have</span>
            <span style={{ textAlign: "right" }}>Total cost</span>
          </div>
          {rows.map(({ s, cost }) => (
            <div key={s.id} className={`row ${s.id === c.supplier ? "pick" : ""}`} style={{ gridTemplateColumns: "1fr 110px 120px 160px" }}>
              <span className="who">{s.id === c.supplier ? `${s.short} · accepted` : s.short}</span>
              <span className="num">{price(lastPrice(s.id))}</span>
              <span className="num">{cost !== null ? "kept ✓" : "broken ✕"}</span>
              <span className="num">{cost !== null ? money(cost) : "-"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function lastPrice(sid: Sid) {
  const rs = replay.events.flatMap((e) => (e.kind === "reply" && e.supplier === sid ? [e.price] : []));
  return rs.at(-1) ?? byId[sid].quote.unit_price ?? 0;
}

function DebriefView() {
  const l = replay.lesson;
  const th = l.threads[0];
  return (
    <div className="view">
      <div className="col">
        <dl className="kv">
          <dt>Filed under</dt>
          <dd>{`${l.goal} · ${l.type.toUpperCase()} · ${l.bidders} bidders · ${l.owners.join(", ")}-owned`}</dd>
          <dt>Our path</dt>
          <dd className="mono" style={{ fontSize: 17 }}>
            {th.ours.map((v) => pct(v)).join(" → ")}
          </dd>
          <dt>Its path</dt>
          <dd className="mono" style={{ fontSize: 17 }}>
            {th.theirs.map((v) => pct(v)).join(" → ")}
          </dd>
          <dt>Never</dt>
          <dd>a supplier's name or an ID</dd>
        </dl>
      </div>
      <div className="col" style={{ display: "grid", alignContent: "center" }}>
        <p className="quote">{`\u201C${l.lesson}\u201D`}</p>
        <p className="quiet" style={{ fontSize: 17, margin: "14px 0 0" }}>
          The next lead researcher on a case like this reads the facts behind it.
        </p>
      </div>
    </div>
  );
}

function FinalView() {
  return (
    <div className="view">
      <div className="col">
        <p className="lede">
          Each case of a wave gets its own team, all at once, within the wave's eight minutes. No one touches the keyboard. The rules that set prices are the same in every team.
        </p>
      </div>
      <div className="col waves">
        {[1, 2, 3, 4, 5].map((w) => (
          <div key={w} className="wave">
            <span className="eyebrow">{`Wave ${w}`}</span>
            {Array.from({ length: 10 }, (_, i) => (
              <svg key={i} width={46} height={34} viewBox="0 0 46 34">
                <rect x={1} y={1} width={44} height={32} rx={8} fill="none" stroke="var(--ink-2)" strokeWidth={1.2} strokeDasharray="3 3" />
                {[11, 23, 35].map((cx) => (
                  <circle key={cx} cx={cx} cy={13} r={3.2} fill="var(--ink-2)" />
                ))}
                <polygon points="23,19 27,21.5 27,26 23,28.5 19,26 19,21.5" fill="var(--ink)" />
              </svg>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
