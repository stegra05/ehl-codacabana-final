// The team as an instrument diagram (ISA-5.1 shapes): circles are model agents, the hexagon is
// code. Lines are information; only e-mails cross the team's boundary.
import { AnimatePresence, motion } from "motion/react";
import { AGENTS, leadBreach, MAX_LEAD, money, price, replay, type Snapshot, type Thread } from "./replay";
import type { Focus } from "./steps";

const P = {
  research: { x: 840, y: 108 },
  rehearsal: { x: 540, y: 284 },
  negotiator: { x: 840, y: 284 },
  analyst: { x: 1150, y: 190 },
  writer: { x: 1150, y: 380 },
  debrief: { x: 700, y: 440 },
};
const HEX = 70;
const ROWS = [130, 280, 430]; // the suppliers' tracks, where the manifold meets them

export const NODE_X: Record<Focus, number> = {
  team: 855,
  records: 158,
  research: P.research.x,
  rehearsal: P.rehearsal.x,
  negotiator: P.negotiator.x,
  analyst: P.analyst.x,
  writer: P.writer.x,
  debrief: P.debrief.x,
  suppliers: 1662,
};

type Anchor = "start" | "middle" | "end";
const EDGES: { id: string; d: string; label: [string, number, number, Anchor?, number?]; memory?: boolean }[] = [
  { id: "records-research", d: "M 268 108 H 798", label: ["orders · contracts · letters · indices", 560, 94] },
  { id: "research-negotiator", d: "M 840 150 V 221", label: ["strategy", 852, 212, "start"] },
  { id: "research-rehearsal", d: "M 840 186 H 540 V 242", label: ["findings", 690, 174] },
  { id: "rehearsal-negotiator", d: "M 582 284 H 766", label: ["opening · pace", 674, 272] },
  { id: "suppliers-analyst", d: "M 1420 190 H 1192", label: ["replies", 1306, 178] },
  { id: "analyst-negotiator", d: "M 1150 232 V 284 H 914", label: ["mood · asks", 1032, 272] },
  { id: "negotiator-writer", d: "M 868 345 V 380 H 1108", label: ["price · terms · facts", 990, 368] },
  { id: "writer-suppliers", d: "M 1192 380 H 1420", label: ["e-mails", 1306, 368] },
  { id: "negotiator-debrief", d: "M 812 345 V 368 H 700 V 398", label: ["outcome", 756, 358] },
  { id: "debrief-research", d: "M 658 440 H 400 V 108", label: ["lessons · next case", 384, 300, "middle", -90], memory: true },
];

type State = "idle" | "done" | "focus";

export function hexPoints(cx: number, cy: number, r: number) {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i;
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  }).join(" ");
}

function Agent(props: {
  at: { x: number; y: number };
  count: string;
  state: State;
  name: string;
  role: string;
  status: string;
  label: { x: number; y: number; anchor: Anchor };
  onSelect: () => void;
}) {
  const { at, label } = props;
  return (
    <g
      className={`node ${props.state}`}
      onClick={props.onSelect}
      role="button"
      tabIndex={0}
      aria-label={props.name}
      onKeyDown={(e) => e.key === "Enter" && props.onSelect()}
    >
      <circle className="halo" cx={at.x} cy={at.y} r={58} />
      <circle className="disc" cx={at.x} cy={at.y} r={40} />
      <text className="count" x={at.x} y={at.y} dy="0.36em" textAnchor="middle">
        {props.count}
      </text>
      <text className="node-name" x={label.x} y={label.y} textAnchor={label.anchor}>
        {props.name}
      </text>
      <text className="node-role" x={label.x} y={label.y + 23} textAnchor={label.anchor}>
        {props.role}
      </text>
      <text className="node-status" x={label.x} y={label.y + 44} textAnchor={label.anchor}>
        {props.status}
      </text>
    </g>
  );
}

export function Schematic({
  snap,
  focus,
  edges,
  onSelect,
}: {
  snap: Snapshot;
  focus: Focus;
  edges: string[];
  onSelect: (f: Focus) => void;
}) {
  const { cut } = snap;
  const state = (key: Focus, done: boolean): State => (focus === key ? "focus" : done ? "done" : "idle");
  const research = replay.events.find((e) => e.kind === "research");
  const seconds = research && research.kind === "research" ? research.until : 0;
  const tuned = Object.values(replay.research).filter((r) => r.rehearsal && r.rehearsal.anchor !== r.rehearsal.default).length;
  const demos = Object.values(replay.research).reduce((n, r) => n + (r.rehearsal?.runs.length ?? 0), 0);
  const reads = snap.events.flatMap((e) => (e.kind === "analyst" ? [e.seconds] : []));
  const avg = reads.length ? reads.reduce((a, b) => a + b, 0) / reads.length : 0;
  const team = focus === "team";

  return (
    <div className="map">
      <svg viewBox="0 0 1920 520" width={1920} height={520}>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--line)" />
          </marker>
          <marker id="arrow-on" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--signal)" />
          </marker>
        </defs>

        <rect className={`boundary ${team ? "focus" : ""}`} x={330} y={30} width={1050} height={470} rx={30} />
        <rect x={350} y={20} width={450} height={20} fill="var(--canvas)" />
        <text className={`boundary-label ${team ? "focus" : ""}`} x={362} y={35}>
          {`PURCHASING TEAM · ${AGENTS} AGENTS · 1 NEGOTIATOR IN CODE`}
        </text>

        {EDGES.map((e) => {
          const on = edges.includes(e.id);
          const [text, lx, ly, anchor = "middle", rotate] = e.label;
          return (
            <g key={e.id}>
              <path className={`edge ${e.memory ? "memory" : ""}`} d={e.d} markerEnd={e.memory ? undefined : "url(#arrow)"} />
              <AnimatePresence>
                {on && (
                  <motion.path
                    className="edge-on"
                    d={e.d}
                    markerEnd={e.memory ? undefined : "url(#arrow-on)"}
                    strokeDasharray={e.memory ? "2 7" : undefined}
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ pathLength: { duration: 0.55, ease: [0.2, 0.7, 0.2, 1] }, opacity: { duration: 0.2 } }}
                  />
                )}
              </AnimatePresence>
              <text
                className={`flow ${on ? "on" : ""}`}
                x={lx}
                y={ly}
                textAnchor={anchor}
                transform={rotate ? `rotate(${rotate} ${lx} ${ly})` : undefined}
              >
                {text.toUpperCase()}
              </text>
            </g>
          );
        })}
        <circle className="joint" cx={840} cy={186} r={4} />
        <circle className="joint" cx={400} cy={108} r={4} />

        {/* the manifold to the suppliers */}
        <line x1={1420} y1={ROWS[0]} x2={1420} y2={ROWS[2]} stroke="var(--line)" strokeWidth={2} />
        {ROWS.map((y) => (
          <line key={y} x1={1420} y1={y} x2={1446} y2={y} stroke="var(--line)" strokeWidth={2} />
        ))}

        <g className={`records ${cut >= 0 ? "done" : ""}`} onClick={() => onSelect("records")} style={{ cursor: "pointer" }}>
          <rect x={48} y={60} width={220} height={96} rx={14} />
          <text className="node-name" x={68} y={96} style={{ fill: "var(--ink)" }}>
            Our records
          </text>
          <text className="node-role" x={68} y={120}>
            orders, contracts, letters,
          </text>
          <text className="node-role" x={68} y={141}>
            indices, scorecards
          </text>
        </g>

        <Agent
          at={P.research}
          count={String(replay.calls.research)}
          state={state("research", cut >= 0)}
          name="Research team"
          role="reads our records"
          status={cut >= 0 ? `${replay.calls.research} agents · ${seconds.toFixed(1)} s` : "waiting"}
          label={{ x: 898, y: 94, anchor: "start" }}
          onSelect={() => onSelect("research")}
        />
        <Agent
          at={P.rehearsal}
          count={String(replay.calls.roleplay)}
          state={state("rehearsal", cut >= 1.5)}
          name="Rehearsal"
          role="role-play, then demo bids"
          status={cut >= 1.5 ? `${demos} demo bids · ${tuned} opening moved` : "waiting"}
          label={{ x: 540, y: 350, anchor: "middle" }}
          onSelect={() => onSelect("rehearsal")}
        />
        <Agent
          at={P.analyst}
          count="1"
          state={state("analyst", snap.reads > 0)}
          name="Live analyst"
          role="reads every reply"
          status={snap.reads ? `${snap.reads} reads · ${avg.toFixed(1)} s` : "waiting"}
          label={{ x: 1094, y: 176, anchor: "end" }}
          onSelect={() => onSelect("analyst")}
        />
        <Agent
          at={P.writer}
          count="1"
          state={state("writer", snap.sent > 0)}
          name="Writer"
          role="model words, code figures"
          status={snap.sent ? `${snap.sent} e-mails · ${snap.modelParagraphs} by model` : "waiting"}
          label={{ x: 1150, y: 446, anchor: "middle" }}
          onSelect={() => onSelect("writer")}
        />
        <Agent
          at={P.debrief}
          count="1"
          state={state("debrief", snap.debriefed)}
          name="Debrief"
          role="writes the lesson"
          status={snap.debriefed ? "1 lesson stored" : "waiting"}
          label={{ x: 756, y: 428, anchor: "start" }}
          onSelect={() => onSelect("debrief")}
        />

        <g
          className={`node ${state("negotiator", snap.sent > 0)}`}
          onClick={() => onSelect("negotiator")}
          role="button"
          tabIndex={0}
          aria-label="Negotiator"
          onKeyDown={(e) => e.key === "Enter" && onSelect("negotiator")}
        >
          <polygon className="halo" points={hexPoints(P.negotiator.x, P.negotiator.y, HEX + 18)} />
          <polygon className="disc" points={hexPoints(P.negotiator.x, P.negotiator.y, HEX)} />
          <text className="hex-name" x={840} y={278} textAnchor="middle">
            Negotiator
          </text>
          <text className="hex-role" x={840} y={300} textAnchor="middle">
            sets every price
          </text>
          <text className="count small hex-status" x={840} y={322} textAnchor="middle">
            {snap.accepted ? "ACCEPTED" : snap.round ? `ROUND ${snap.round}` : "CODE"}
          </text>
        </g>

        <g transform="translate(48 420)">
          <circle className="legend-mark" cx={9} cy={0} r={8} />
          <text className="legend" x={28} y={5}>
            MODEL AGENT
          </text>
          <polygon className="legend-mark" points={hexPoints(9, 30, 9)} />
          <text className="legend" x={28} y={35}>
            CODE
          </text>
          <line x1={0} y1={60} x2={18} y2={60} stroke="var(--ink-2)" strokeWidth={2} strokeDasharray="2 5" strokeLinecap="round" />
          <text className="legend" x={28} y={65}>
            NEXT CASE
          </text>
        </g>
      </svg>
      <Threads snap={snap} focus={focus === "suppliers"} onSelect={() => onSelect("suppliers")} />
    </div>
  );
}

// ------------------------------------------------------------------ the suppliers' threads

const LOW = 26;
const HIGH = 40;
const W = 420;
const xOf = (p: number) => ((p - LOW) / (HIGH - LOW)) * W;

const STATUS: Record<Thread["status"], string> = {
  waiting: "waiting",
  quoted: "quote",
  countered: "counter",
  agreed: "agreed",
  accepted: "deal",
};

function Track({ th }: { th: Thread }) {
  const ours = th.ours.at(-1);
  const theirs = th.theirs.at(-1);
  const met = ours !== undefined && theirs !== undefined && Math.abs(ours - theirs) < 0.005;
  const spring = { type: "spring", stiffness: 170, damping: 26 } as const;
  return (
    <svg className="track" width={W} height={66} viewBox={`0 0 ${W} 66`}>
      {[28, 30, 32, 34, 36, 38].map((p) => (
        <line key={p} className="tick" x1={xOf(p)} x2={xOf(p)} y1={27} y2={41} />
      ))}
      <line className="axis" x1={0} x2={W} y1={34} y2={34} />
      {ours !== undefined && theirs !== undefined && !met && (
        <motion.rect
          className="gap"
          y={29}
          height={10}
          rx={5}
          initial={false}
          animate={{ x: xOf(ours), width: Math.max(0, xOf(theirs) - xOf(ours)) }}
          transition={spring}
        />
      )}
      {[...th.theirs.slice(0, -1), ...th.ours.slice(0, -1)].map((p, i) => (
        <line key={i} className="trail" x1={xOf(p)} x2={xOf(p)} y1={28} y2={40} />
      ))}
      {theirs !== undefined && !met && (
        <>
          <motion.circle className="theirs" cy={34} r={7} initial={false} animate={{ cx: xOf(theirs) }} transition={spring} />
          <motion.text y={17} textAnchor="middle" initial={false} animate={{ x: xOf(theirs) }} transition={spring}>
            {price(theirs)}
          </motion.text>
        </>
      )}
      {ours !== undefined && (
        <>
          <motion.circle className="ours" cy={34} r={met ? 8 : 7} initial={false} animate={{ cx: xOf(ours) }} transition={spring} />
          <motion.text y={62} textAnchor="middle" initial={false} animate={{ x: xOf(ours) }} transition={spring}>
            {price(ours)}
          </motion.text>
        </>
      )}
    </svg>
  );
}

function Threads({ snap, focus, onSelect }: { snap: Snapshot; focus: boolean; onSelect: () => void }) {
  return (
    <div className={`threads ${focus ? "focus" : ""}`}>
      <div className="threads-head">
        <span className="eyebrow">Suppliers</span>
        <span className="eyebrow legend-inline">
          <svg width={14} height={14} aria-hidden>
            <circle cx={7} cy={7} r={5.5} fill="var(--ink)" />
          </svg>
          ours
          <svg width={14} height={14} aria-hidden>
            <circle cx={7} cy={7} r={5} fill="var(--canvas)" stroke="var(--ink)" strokeWidth={2} />
          </svg>
          theirs
        </span>
      </div>
      {snap.threads.map((th) => (
        <div key={th.supplier.id} className={`thread ${th.status}`} onClick={onSelect}>
          <div className="thread-head">
            <span className="thread-name">{th.supplier.short}</span>
            {leadBreach(th.lead) && <span className="chip breach">{`lead ${th.lead} d · max ${MAX_LEAD}`}</span>}
            <span className={`chip ${th.status}`}>{STATUS[th.status]}</span>
          </div>
          <Track th={th} />
          <div className="thread-foot">
            <span>{th.quote !== null ? `quote ${price(th.quote)}` : "no quote yet"}</span>
            <span>{th.standing !== null ? `total cost ${money(th.standing)}` : th.quote !== null ? "breaks a must-have" : ""}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
