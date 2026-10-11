import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { agents, lanes } from "./steps";
import { events, type Stage } from "./replay";

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    research: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 5 5M7 10h6M10 7v6" />
      </>
    ),
    rehearsal: (
      <>
        <path d="M4 4h12v9H9l-4 3v-3H4zM10 17h5l4 3v-3h2V9h-2" />
      </>
    ),
    analyst: (
      <>
        <path d="M4 17V7m5 13V4m5 12V8m5 10V6" />
      </>
    ),
    negotiator: (
      <>
        <path d="m12 2 9 5v10l-9 5-9-5V7zM8 9l-3 3 3 3m8-6 3 3-3 3m-3-7-2 8" />
      </>
    ),
    writer: (
      <>
        <path d="M3 6h18v13H3zM3 6l9 7 9-7" />
      </>
    ),
    close: (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6" />
      </>
    ),
    debrief: (
      <>
        <path d="M5 5h14v15H5zM9 3h6v4H9zM8 11h8m-8 4h5" />
      </>
    ),
    play: <path d="m8 4 12 8-12 8z" />,
    pause: (
      <>
        <path d="M8 4v16M16 4v16" />
      </>
    ),
    reset: (
      <>
        <path d="M4 10a8 8 0 1 1 1 8M4 4v6h6" />
      </>
    ),
    next: (
      <>
        <path d="m8 5 7 7-7 7M19 5v14" />
      </>
    ),
    back: <path d="m15 5-7 7 7 7" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    check: <path d="m5 12 4 4L19 6" />,
    x: <path d="m6 6 12 12M6 18 18 6" />,
    data: (
      <>
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v12c0 4 16 4 16 0V5M4 11c0 4 16 4 16 0" />
      </>
    ),
    expand: (
      <>
        <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" />
      </>
    ),
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6m0-10v1" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.info}
    </svg>
  );
}

type NodeBox = {
  left: number;
  right: number;
  top: number;
  bottom: number;
  x: number;
  y: number;
};
type Layout = {
  width: number;
  height: number;
  nodes: Record<string, NodeBox>;
  narrow: boolean;
};

// Measure rendered cards, so the edges stay attached across wrapping, fonts and breakpoints.
function useConnections() {
  const ref = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  useLayoutEffect(() => {
    const container = ref.current;
    if (!container) return;
    const measure = () => {
      const root = container.getBoundingClientRect();
      const nodes: Record<string, NodeBox> = {};
      container.querySelectorAll<HTMLElement>("[data-node]").forEach((node) => {
        const r = node.getBoundingClientRect();
        nodes[node.dataset.node!] = {
          left: r.left - root.left,
          right: r.right - root.left,
          top: r.top - root.top,
          bottom: r.bottom - root.top,
          x: r.left - root.left + r.width / 2,
          y: r.top - root.top + r.height / 2,
        };
      });
      setLayout({
        width: root.width,
        height: root.height,
        nodes,
        narrow: window.innerWidth <= 620,
      });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    container
      .querySelectorAll("[data-node]")
      .forEach((node) => observer.observe(node));
    measure();
    return () => observer.disconnect();
  }, []);
  return { ref, layout };
}

function Connections({
  layout,
  current,
}: {
  layout: Layout | null;
  current?: Stage;
}) {
  if (!layout || layout.narrow) return null;
  const n = layout.nodes;
  if (
    !n.records ||
    !n.research ||
    !n.rehearsal ||
    !n.analyst ||
    !n.negotiator ||
    !n.writer ||
    !n.suppliers ||
    !n.close ||
    !n.debrief ||
    !n.memory
  )
    return null;
  const down = (a: NodeBox, b: NodeBox) =>
    `M ${a.x} ${a.bottom} V ${b.top - 5}`;
  const across = (a: NodeBox, b: NodeBox, offset = 0) => {
    const mid = (a.right + b.left) / 2 + offset;
    return `M ${a.right} ${a.y} H ${mid} V ${b.y} H ${b.left - 5}`;
  };
  const feed = `M ${n.rehearsal.right} ${n.rehearsal.y} H ${n.negotiator.left - 16} V ${n.negotiator.bottom - 18} H ${n.negotiator.left - 5}`;
  const loopX = n.writer.right + 20;
  const reply = `M ${n.suppliers.right} ${n.suppliers.y} H ${loopX} V ${n.analyst.y} H ${n.analyst.right + 5}`;
  const memoryY = layout.height - 24;
  const memory = `M ${n.memory.x} ${n.memory.bottom} V ${memoryY} H ${n.research.left - 13} V ${n.research.y} H ${n.research.left - 5}`;
  const links = [
    {
      id: "records",
      path: down(n.records, n.research),
      stage: "research",
      kind: "handoff",
    },
    {
      id: "findings",
      path: down(n.research, n.rehearsal),
      stage: "rehearsal",
      kind: "handoff",
    },
    {
      id: "strategy",
      path: across(
        n.research,
        { ...n.negotiator, y: n.negotiator.top + 29 },
        -8,
      ),
      stage: "negotiator",
      kind: "handoff",
    },
    { id: "playbook", path: feed, stage: "negotiator", kind: "handoff" },
    {
      id: "tactic",
      path: down(n.analyst, n.negotiator),
      stage: "negotiator",
      kind: "handoff",
    },
    {
      id: "proposal",
      path: down(n.negotiator, n.writer),
      stage: "writer",
      kind: "handoff",
    },
    {
      id: "email",
      path: down(n.writer, n.suppliers),
      stage: "writer",
      kind: "handoff",
    },
    { id: "reply", path: reply, stage: "analyst", kind: "reply" },
    {
      id: "close",
      path: across(n.negotiator, n.close, 12),
      stage: "close",
      kind: "handoff",
    },
    {
      id: "outcome",
      path: down(n.close, n.debrief),
      stage: "debrief",
      kind: "handoff",
    },
    {
      id: "save",
      path: down(n.debrief, n.memory),
      stage: "debrief",
      kind: "handoff",
    },
    { id: "recall", path: memory, stage: "research", kind: "memory" },
  ];
  const labels = [
    {
      text: "strategy",
      x: (n.research.right + n.negotiator.left) / 2,
      y: n.research.y - 10,
    },
    {
      text: "playbook",
      x: (n.rehearsal.right + n.negotiator.left) / 2,
      y: n.rehearsal.y + 17,
    },
    {
      text: "terms",
      x: (n.negotiator.right + n.close.left) / 2,
      y: n.negotiator.y - 10,
    },
    { text: "replies", x: loopX, y: n.writer.bottom + 13, kind: "reply" },
    {
      text: "outcome",
      x: n.close.x,
      y: (n.close.bottom + n.debrief.top) / 2,
      kind: "handoff",
    },
    {
      text: "memory → next similar case",
      x: (n.research.x + n.memory.x) / 2,
      y: memoryY,
      kind: "memory",
    },
  ];
  return (
    <svg
      className="connections"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      aria-hidden="true"
    >
      <defs>
        {["handoff", "reply", "memory", "active"].map((kind) => (
          <marker
            id={`arrow-${kind}`}
            key={kind}
            viewBox="0 0 10 10"
            refX="7"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path
              d="M 1 1 L 8 5 L 1 9"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              className={`arrow-${kind}`}
            />
          </marker>
        ))}
      </defs>
      {links.map((link) => (
        <g key={link.id}>
          <path className="edge-casing" d={link.path} />
          <path
            className={`edge edge-${link.kind} ${link.stage === current ? "edge-active" : ""}`}
            d={link.path}
            markerEnd={`url(#arrow-${link.stage === current ? "active" : link.kind})`}
          />
        </g>
      ))}
      {labels.map((label) => (
        <g
          key={label.text}
          className={`edge-label label-${label.kind ?? "handoff"}`}
          transform={`translate(${label.x} ${label.y})`}
        >
          <rect
            x={-label.text.length * 2.7 - 4}
            y={-7}
            width={label.text.length * 5.4 + 8}
            height={14}
            rx={3}
          />
          <text textAnchor="middle" dominantBaseline="central">
            {label.text}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function Schematic({
  index,
  playing,
  onSelect,
}: {
  index: number;
  playing: boolean;
  onSelect: (id: Stage) => void;
}) {
  const current = events[index - 1]?.stage;
  const visited = new Set(events.slice(0, index).map((e) => e.stage));
  const complete = index === events.length;
  const { ref, layout } = useConnections();
  return (
    <div className="architecture connected-architecture">
      <div className="orchestrator">
        <span className="orchestrator-title">
          <span className="status-dot" /> Runner{" "}
          <span className="code-tag">CODE</span>
        </span>
        <span>
          Orchestrates the case <span className="separator">/</span> oldest
          reply first <span className="separator">/</span> 60s reply clock
        </span>
      </div>
      <div className="flow-canvas" ref={ref}>
        <Connections layout={layout} current={complete ? undefined : current} />
        <div className="lanes">
          {lanes.map((lane, laneIndex) => (
            <section
              className={`lane lane-${laneIndex}`}
              key={lane.name}
              aria-label={lane.name}
            >
              <header className="lane-heading">
                <span className="lane-number">0{laneIndex + 1}</span>
                <div>
                  <h3>{lane.name}</h3>
                  <p>{lane.label}</p>
                </div>
              </header>
              {laneIndex === 0 && (
                <div className="data-source" data-node="records">
                  <Icon name="data" size={17} />
                  <span>Records, facts & prior outcomes</span>
                </div>
              )}
              <div className="lane-nodes">
                {lane.ids.map((id, i) => {
                  const agent = agents[id];
                  const active = !complete && current === id;
                  const done = visited.has(id) && !active;
                  return (
                    <div className="node-wrap" key={id}>
                      {i > 0 && (
                        <div className="connector" aria-hidden="true">
                          <span />
                        </div>
                      )}
                      <button
                        data-node={id}
                        className={`agent-card agent-${agent.kind.toLowerCase()} ${id === "negotiator" ? "engine" : ""} ${active ? "active" : ""} ${done ? "done" : ""} ${active && playing ? "running" : ""}`}
                        onClick={() => onSelect(id)}
                        aria-label={`Inspect ${agent.name}`}
                        aria-current={active ? "step" : undefined}
                      >
                        <div className="agent-top">
                          <span className="agent-icon">
                            <Icon name={id} size={21} />
                          </span>
                          <span
                            className={`kind kind-${agent.kind.toLowerCase()}`}
                          >
                            {agent.kind === "Code" ? "◇" : "○"} {agent.kind}
                          </span>
                          <span className="agent-state">
                            {active ? (
                              <span className="status-dot" />
                            ) : done ? (
                              <Icon name="check" size={15} />
                            ) : (
                              <span className="inspect-plus">+</span>
                            )}
                          </span>
                        </div>
                        <h4>{agent.name}</h4>
                        <p>{agent.description}</p>
                        {id === "research" && (
                          <div className="research-roles">
                            <div>
                              <span>Economics</span>
                              <span>Persona</span>
                              <span>History</span>
                              <span>Leverage</span>
                            </div>
                            <strong>↓ Lead researcher</strong>
                          </div>
                        )}
                        {id === "rehearsal" && (
                          <div className="role-exchange">
                            <span>Supplier role</span>
                            <Icon name="arrow" size={12} />
                            <span>Buyer role</span>
                          </div>
                        )}
                        {id === "negotiator" && (
                          <div className="engine-checks">
                            <span>total_cost</span>
                            <span>must_haves_ok</span>
                          </div>
                        )}
                      </button>
                    </div>
                  );
                })}
              </div>
              {laneIndex === 0 && (
                <div className="handoff-caption">
                  <Icon name="arrow" size={14} />
                  <span>Strategy + playbook → decision engine</span>
                </div>
              )}
              {laneIndex === 1 && (
                <>
                  <div className="connector" aria-hidden="true">
                    <span />
                  </div>
                  <div className="supplier-endpoint" data-node="suppliers">
                    <Icon name="writer" size={16} />
                    <div>
                      <strong>Supplier threads</strong>
                      <span>Emails out · replies back to analyst</span>
                    </div>
                  </div>
                </>
              )}
              {laneIndex === 2 && (
                <>
                  <div className="connector" aria-hidden="true">
                    <span />
                  </div>
                  <div className="memory-endpoint" data-node="memory">
                    <Icon name="data" size={16} />
                    <div>
                      <strong>Saved outcomes</strong>
                      <span>Recalled for the next similar case</span>
                    </div>
                  </div>
                </>
              )}
            </section>
          ))}
        </div>
        <div className="mobile-memory">
          ↶ Saved outcomes return to research for the next similar case
        </div>
      </div>
      <div className="architecture-footer">
        <span>
          <i className="legend-model" /> Model reasoning
        </span>
        <span>
          <i className="legend-code" /> Code & data
        </span>
        <span className="legend-flow">→ Handoff</span>
        <span className="legend-reply">↺ Supplier replies</span>
        <span className="inspect-hint">
          Select a component <Icon name="info" size={14} />
        </span>
      </div>
      <p className="sr-only">
        Records feed research. Specialist findings feed the lead researcher and
        rehearsal. The lead's strategy and the rehearsal playbook feed the
        decision engine. Supplier replies feed the live analyst, which advises
        the decision engine. The decision engine sends approved terms to the
        writer, which emails the suppliers. The decision engine also feeds the
        close gate. The close gate passes the outcome to debrief, which saves
        results for the next similar case's research.
      </p>
    </div>
  );
}

export function Progress({ index }: { index: number }) {
  return (
    <div
      className="progress-track"
      style={
        { "--progress": `${(index / events.length) * 100}%` } as CSSProperties
      }
    >
      <div />
    </div>
  );
}
