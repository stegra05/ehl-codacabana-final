// The monitor: one fixed 1920 x 1080 stage scaled to the screen. → or the clicker steps the
// replay, a click on a node inspects it, Esc returns to the step, F toggles fullscreen.
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { clock, money, pct, replay, snapshot, type Sid, type Snapshot } from "./replay";
import { NODE_X, Schematic } from "./Schematic";
import { type Focus, nodeView, type Step, steps, type View } from "./steps";
import { Body, eyebrow, TABBED } from "./views";

function useScale() {
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const fit = () => setScale(Math.min(window.innerWidth / 1920, window.innerHeight / 1080));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  return scale;
}

export default function App() {
  const scale = useScale();
  const [index, setIndex] = useState(() => Math.max(0, Math.min(steps.length - 1, Number(new URLSearchParams(location.search).get("step")) || 0)));
  const [picked, setPicked] = useState<Focus | null>(null); // a node clicked: inspect it
  const step = steps[index];
  const snap = useMemo(() => snapshot(step.cut), [step.cut]);
  const focus = picked ?? step.focus;
  const view: View = picked ? nodeView[picked] : step.view;
  const edges = picked ? [] : step.edges;

  useEffect(() => {
    const go = (d: number) => {
      setPicked(null);
      setIndex((i) => Math.max(0, Math.min(steps.length - 1, i + d)));
    };
    const onKey = (e: KeyboardEvent) => {
      if (["ArrowRight", "PageDown", " ", "Enter"].includes(e.key)) {
        e.preventDefault();
        go(1);
      } else if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) {
        e.preventDefault();
        go(-1);
      } else if (e.key === "Home") go(-steps.length);
      else if (e.key === "End") go(steps.length);
      else if (e.key === "Escape") setPicked(null);
      else if (e.key === "f" || e.key === "F") {
        if (document.fullscreenElement) document.exitFullscreen();
        else document.documentElement.requestFullscreen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="viewport">
      <div className="stage" style={{ transform: `translate(-50%, -50%) scale(${scale})` }}>
        <TopBar snap={snap} />
        <Schematic snap={snap} focus={focus} edges={edges} onSelect={(f) => setPicked(f === step.focus ? null : f)} />
        <Inspector step={step} view={view} focus={focus} snap={snap} picked={picked !== null} />
        <Timeline index={index} onJump={(i) => (setPicked(null), setIndex(i))} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ top bar

function TopBar({ snap }: { snap: Snapshot }) {
  const k = replay.case;
  const now = steps.findIndex((s) => s.cut === snap.cut);
  const trend = steps.map((s) => snapshot(s.cut).best);
  const must = k.must_haves.find((m) => m.field === "lead_time_days");
  return (
    <header className="topbar">
      <div className="brand">
        <svg width={40} height={40} viewBox="0 0 40 40" aria-hidden>
          <rect x={2} y={2} width={36} height={36} rx={9} fill="none" stroke="var(--ink)" strokeWidth={1.8} strokeDasharray="4 3.2" />
          <circle cx={13} cy={15} r={3.4} fill="var(--ink)" />
          <circle cx={27} cy={15} r={3.4} fill="var(--ink)" />
          <polygon points="20,21 25,24 25,30 20,33 15,30 15,24" fill="var(--signal)" />
        </svg>
        <div>
          <div className="brand-name">Purchasing team</div>
          <div className="eyebrow" style={{ fontSize: 13 }}>
            Hollerau Pumpenwerke · monitor
          </div>
        </div>
      </div>
      <div className="case">
        <span className="case-id">{k.id}</span>
        <div style={{ minWidth: 0 }}>
          <div className="case-title">{k.title}</div>
          <div className="case-meta">
            {`${replay.suppliers.length} suppliers · ${k.need_per_year.toLocaleString("en-US")} a year · ${k.horizon_years * 12} months${must ? ` · lead time ≤ ${must.value} days` : ""}`}
          </div>
        </div>
      </div>
      <div className="kpi">
        <div className="eyebrow">Best offer · total cost</div>
        <div className={`kpi-value ${snap.best === null ? "empty" : ""}`}>{snap.best !== null ? money(snap.best) : "no offer yet"}</div>
        <div className="kpi-side">
          <Spark values={trend} now={now} />
          <div className="kpi-delta">
            {snap.best === null ? "" : snap.best < replay.close.c_open ? `${pct(snap.best / replay.close.c_open - 1)} vs. best quote` : "best quote"}
          </div>
        </div>
      </div>
      <div className="session">
        <div className="eyebrow">
          <span className="replay-dot" />
          {`Replay · session ${replay.session.id.slice(0, 8)}`}
        </div>
        <div className="clock">{clock(snap.t)}</div>
      </div>
    </header>
  );
}

function Spark({ values, now }: { values: (number | null)[]; now: number }) {
  // the scale covers the whole replay, so it never jumps; only the past is drawn
  const W = 132;
  const H = 30;
  const finite = values.filter((v): v is number => v !== null);
  const lo = Math.min(...finite);
  const hi = Math.max(...finite);
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => 3 + ((hi - v) / (hi - lo || 1)) * (H - 6);
  const pts = values.flatMap((v, i) => (v !== null && i <= now ? [`${x(i).toFixed(1)},${y(v).toFixed(1)}`] : []));
  const cur = values[now];
  return (
    <svg width={W} height={H} aria-hidden>
      <line x1={0} x2={W} y1={H - 1} y2={H - 1} stroke="var(--rule)" strokeWidth={1} />
      <polyline points={pts.join(" ")} fill="none" stroke="var(--ink-2)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {cur !== null && cur !== undefined && <circle cx={x(now)} cy={y(cur)} r={4.5} fill="var(--signal)" stroke="var(--canvas)" strokeWidth={2} />}
    </svg>
  );
}

// ------------------------------------------------------------------ inspector

function Inspector({ step, view, focus, snap, picked }: { step: Step; view: View; focus: Focus; snap: Snapshot; picked: boolean }) {
  const reduce = useReducedMotion();
  const tabbed = TABBED.includes(view);
  const [sid, setSid] = useState<Sid>(step.supplier ?? replay.close.supplier);
  useEffect(() => setSid(step.supplier ?? replay.close.supplier), [step.supplier, view]);
  const headline = picked ? nodeHeadline(focus) : step.headline;
  const key = `${view}-${step.key}-${picked}`;
  return (
    <section className="inspector">
      <motion.div
        className="notch"
        initial={false}
        animate={{ x: NODE_X[focus] - 48 }}
        transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 32 }}
        style={{ left: 48 }}
      />
      <div className="ins-head">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={key}
            className="ins-title"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: reduce ? 0 : 0.2, ease: [0.2, 0.7, 0.2, 1] }}
          >
            <div className="eyebrow">{eyebrow(view, snap)}</div>
            <div className="headline">{headline}</div>
          </motion.div>
        </AnimatePresence>
        {tabbed && (
          <div className="tabs" role="tablist">
            {replay.suppliers.map((s) => (
              <button key={s.id} role="tab" aria-selected={s.id === sid} className={`tab ${s.id === sid ? "on" : ""}`} onClick={() => setSid(s.id)}>
                {s.short}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="ins-body">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={`${key}-${sid}`}
            style={{ position: "absolute", inset: 0 }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.18 }}
          >
            <Body view={view} snap={snap} sid={sid} />
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  );
}

const NODE_HEADLINE: Record<Focus, string> = {
  team: "One case, one purchasing team",
  records: "Everything the research team reads",
  research: "Four specialists read our records on each supplier",
  rehearsal: "Role-played suppliers, demo bids in code",
  negotiator: "Code sets every price",
  analyst: "The analyst reads every supplier e-mail",
  writer: "A model writes the words, code every figure",
  debrief: "One lesson for the next case like this",
  suppliers: "Where each supplier stands",
};
const nodeHeadline = (f: Focus) => NODE_HEADLINE[f];

// ------------------------------------------------------------------ timeline

function Timeline({ index, onJump }: { index: number; onJump: (i: number) => void }) {
  const W = 1824;
  const gap = W / (steps.length - 1);
  const x = (i: number) => i * gap;
  const phases = steps.reduce<{ phase: string; from: number; to: number }[]>((acc, s, i) => {
    const last = acc.at(-1);
    if (last && last.phase === s.phase) last.to = i;
    else acc.push({ phase: s.phase, from: i, to: i });
    return acc;
  }, []);
  return (
    <footer className="timeline">
      <svg width={W} height={112} viewBox={`0 0 ${W} 112`}>
        {phases.map((p) => (
          <g key={p.phase}>
            <line className="phase-rule" x1={x(p.from) - (p.from ? gap / 2 - 12 : 0)} x2={x(p.to) + (p.to < steps.length - 1 ? gap / 2 - 12 : 0)} y1={24} y2={24} />
            <text className="phase" x={x(p.from) - (p.from ? gap / 2 - 12 : 0)} y={16}>
              {p.phase.toUpperCase()}
            </text>
          </g>
        ))}
        <line className="rail" x1={0} x2={W} y1={52} y2={52} />
        <motion.line
          className="rail-done"
          x1={0}
          y1={52}
          y2={52}
          initial={false}
          animate={{ x2: x(index) }}
          transition={{ type: "spring", stiffness: 220, damping: 32 }}
        />
        {steps.map((s, i) => {
          const t = snapshot(s.cut).t;
          return (
            <g key={s.key} className={`step ${i < index ? "past" : i === index ? "now" : ""}`} onClick={() => onJump(i)}>
              <rect x={x(i) - gap / 2} y={30} width={gap} height={80} fill="transparent" />
              <circle className="step-dot" cx={x(i)} cy={52} r={i === index ? 9 : 6} />
              <text className="step-label" x={x(i)} y={84} textAnchor={i === 0 ? "start" : i === steps.length - 1 ? "end" : "middle"}>
                {s.label.toUpperCase()}
              </text>
              <text className="step-time" x={x(i)} y={102} textAnchor={i === 0 ? "start" : i === steps.length - 1 ? "end" : "middle"}>
                {s.key === "final" ? "" : clock(t)}
              </text>
            </g>
          );
        })}
      </svg>
    </footer>
  );
}

