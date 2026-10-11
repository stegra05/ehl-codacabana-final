import { useEffect, useRef, useState } from "react";
import { agents } from "./steps";
import {
  events,
  money,
  price,
  replay,
  supplierName,
  type Stage,
  threadEntries,
  type ThreadEntry,
  playbackSeconds,
  dealOutcome,
} from "./replay";
import { Icon } from "./Schematic";
import { LiveThreadLine, supplierLabel, useAutoFollow } from "./LiveThread";

export function DealSummary({ index }: { index: number }) {
  const outcome = dealOutcome(index);
  if (!outcome) return null;
  return (
    <section
      className="deal-summary"
      aria-label="Final negotiation outcome"
      aria-live="polite"
    >
      <div className="deal-summary-supplier">
        <span className="eyebrow">
          <Icon name="check" size={14} /> Deal agreed
        </span>
        <strong>{outcome.supplier}</strong>
        <span>{outcome.months}-month contract</span>
      </div>
      <div className="deal-summary-price">
        <span>Agreed unit price</span>
        <strong>
          {price(outcome.unitPrice)} <small>/ unit</small>
        </strong>
        <span>The accepted supplier offer</span>
      </div>
      <div className="deal-summary-savings">
        <span>
          {outcome.savings >= 0 ? "Total savings" : "Cost increase"} ·{" "}
          {outcome.months} months
        </span>
        <strong>
          {price(Math.abs(outcome.savings))}
          {outcome.savingsPercent != null && (
            <small>
              {Math.abs(outcome.savingsPercent).toFixed(1)}%{" "}
              {outcome.savings >= 0 ? "saved" : "increase"}
            </small>
          )}
        </strong>
        <span>
          Opening {price(outcome.openingCost)} → agreed{" "}
          {price(outcome.totalCost)}
        </span>
      </div>
    </section>
  );
}

export function RunPanel({
  index,
  playing,
  onOpenThread,
}: {
  index: number;
  playing: boolean;
  onOpenThread: (sid: string) => void;
}) {
  const [sid, setSid] = useState(replay.suppliers[0].id);
  const event = events[index - 1];
  const state = event?.suppliers ?? {};
  const current = state[sid];
  const closed = events.slice(0, index).some((e) => e.stage === "close");
  const cost =
    closed && replay.result.c_deal != null ? replay.result.c_deal : event?.best;
  return (
    <aside className="run-panel live-run-panel" aria-label="Live test run">
      <div className="panel-heading">
        <span className="eyebrow">Short test run</span>
        <span className="small-badge">
          {replay.case.round_limit} rounds · ~{playbackSeconds}s
        </span>
      </div>
      <div className="live-case-heading">
        <div>
          <h2>{replay.case.title.split(":")[0]}</h2>
          <p>
            {replay.suppliers.length} suppliers ·{" "}
            {replay.case.buyer.need_per_year.toLocaleString("en-GB")} units /
            year
          </p>
        </div>
        <span className="small-badge">S02</span>
      </div>
      <div className="live-case-cost">
        <span>
          {closed ? "Accepted total cost" : "Best standing total cost"}
        </span>
        <strong>{cost == null ? "Awaiting quotes" : money(cost)}</strong>
      </div>
      <div
        className="supplier-tabs"
        role="tablist"
        aria-label="Supplier conversations"
      >
        {replay.suppliers.map((supplier, i) => (
          <button
            key={supplier.id}
            id={`supplier-tab-${i}`}
            role="tab"
            aria-selected={sid === supplier.id}
            aria-controls="live-thread-panel"
            tabIndex={sid === supplier.id ? 0 : -1}
            onClick={() => setSid(supplier.id)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              e.preventDefault();
              const next =
                (i +
                  (e.key === "ArrowRight" ? 1 : -1) +
                  replay.suppliers.length) %
                replay.suppliers.length;
              setSid(replay.suppliers[next].id);
              document.getElementById(`supplier-tab-${next}`)?.focus();
            }}
          >
            <span
              className={`supplier-tab-dot ${playing && event?.supplier === supplier.id ? "is-live" : ""}`}
            />
            {supplierLabel(supplier.id)}
            <small>
              {
                threadEntries(index, supplier.id).filter(
                  (entry) => entry.message,
                ).length
              }
            </small>
          </button>
        ))}
      </div>
      <div
        id="live-thread-panel"
        role="tabpanel"
        aria-labelledby={`supplier-tab-${replay.suppliers.findIndex((supplier) => supplier.id === sid)}`}
      >
        <div className="live-supplier-title">
          <h3>{supplierName(sid)}</h3>
          <span>
            {closed
              ? current?.status === "accepted"
                ? "Accepted"
                : "Not selected"
              : !current
                ? "Awaiting quotes"
                : current.status === "agreed"
                  ? "Agreed"
                  : "Negotiating"}
          </span>
        </div>
        <div className="live-price-pair">
          <div className="theirs">
            <span>{closed ? "Last supplier offer" : "Supplier offer"}</span>
            <strong key={current?.price}>
              {current?.price != null ? price(current.price) : "—"}
            </strong>
          </div>
          <Icon name="arrow" size={15} />
          <div className="ours">
            <span>{closed ? "Our last proposal" : "Our proposal"}</span>
            <strong key={current?.ours}>
              {current?.ours != null ? price(current.ours) : "—"}
            </strong>
          </div>
        </div>
        <LiveThreadLine sid={sid} index={index} playing={playing} />
        <button
          className="thread-button live-expand"
          onClick={() => onOpenThread(sid)}
          aria-label={`Open conversation with ${supplierName(sid)}`}
        >
          <Icon name="expand" size={14} /> Expand thread & offer history{" "}
          <Icon name="arrow" size={14} />
        </button>
      </div>
      <p className="live-disclaimer">
        Local simulator trace · scripted model responses · n = 1
      </p>
    </aside>
  );
}

export function Activity({
  index,
  onInspect,
}: {
  index: number;
  onInspect: (id: Stage) => void;
}) {
  const event = events[index - 1];
  return (
    <div className="activity" aria-live="polite" aria-atomic="true">
      <span className={`activity-icon ${event ? "started" : ""}`}>
        <Icon name={event?.stage ?? "play"} size={21} />
      </span>
      <div>
        <span className="eyebrow">
          {event
            ? `Step ${String(index).padStart(2, "0")} · ${agents[event.stage].name}`
            : "Ready when you are"}
        </span>
        <h3>{event?.title ?? "Follow one case through the whole team"}</h3>
        <p>
          {event?.summary ??
            "Start the test run to watch quotes become checked offers, a decision and a lesson."}
        </p>
      </div>
      {event && (
        <button className="text-button" onClick={() => onInspect(event.stage)}>
          Inspect <Icon name="arrow" size={16} />
        </button>
      )}
    </div>
  );
}

export function RunLog({
  index,
  onJump,
}: {
  index: number;
  onJump: (step: number) => void;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest", behavior: "instant" });
  }, [index]);
  return (
    <div className="run-log">
      <div className="log-intro">
        <Icon name="data" />
        <div>
          <h3>Every handoff, in order</h3>
          <p>
            Events from the generated test run. Select an event to return to it.
          </p>
        </div>
      </div>
      {index === 0 ? (
        <div className="log-empty">
          <Icon name="play" size={32} />
          <h3>No events yet</h3>
          <p>Start the test run or advance one step.</p>
        </div>
      ) : (
        <ol>
          {events.slice(0, index).map((event, i) => (
            <li key={i}>
              <button
                onClick={() => onJump(i + 1)}
                aria-current={i + 1 === index ? "step" : undefined}
              >
                <span className="log-number">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  className={`log-icon ${agents[event.stage].kind === "Code" ? "log-code" : ""}`}
                >
                  <Icon name={event.stage} size={18} />
                </span>
                <span className="log-copy">
                  <strong>{event.title}</strong>
                  <span>
                    {event.supplier
                      ? supplierName(event.supplier)
                      : agents[event.stage].name}
                  </span>
                </span>
                <span className="log-stage">{agents[event.stage].kind}</span>
                <Icon name="arrow" size={16} />
              </button>
            </li>
          ))}
        </ol>
      )}
      <div ref={bottom} />
    </div>
  );
}

export function Inspector({
  selected,
  index,
  onClose,
}: {
  selected: Stage;
  index: number;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const agent = agents[selected];
  const event = events
    .slice(0, index)
    .reverse()
    .find((e) => e.stage === selected);
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    element?.showModal();
    return () => {
      element?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="inspector-dialog"
      aria-labelledby="inspector-title"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="dialog-content">
        <div className="dialog-top">
          <span className={`kind kind-${agent.kind.toLowerCase()}`}>
            {agent.kind === "Code" ? "◇" : "○"} {agent.kind} component
          </span>
          <button
            className="icon-button"
            aria-label="Close component details"
            onClick={onClose}
          >
            <Icon name="x" />
          </button>
        </div>
        <span className="dialog-icon">
          <Icon name={selected} size={28} />
        </span>
        <h2 id="inspector-title">{agent.name}</h2>
        <p className="dialog-role">{agent.role}</p>
        <div className="io-grid">
          <div>
            <span className="eyebrow">Receives</span>
            <p>{agent.inputs}</p>
          </div>
          <div>
            <span className="eyebrow">Produces</span>
            <p>{agent.outputs}</p>
          </div>
        </div>
        <div className="module-list">
          <span className="eyebrow">Implementation</span>
          <div>
            {agent.modules.map((module) => (
              <code key={module}>{module}</code>
            ))}
          </div>
        </div>
        <div className="event-detail">
          <div className="event-detail-heading">
            <span className="eyebrow">Latest output in this playback</span>
            <span className="small-badge">
              {event ? "Recorded" : "Pending"}
            </span>
          </div>
          {event ? (
            <>
              <h3>{event.title}</h3>
              <p>
                {event.supplier ? supplierName(event.supplier) : event.summary}
              </p>
              <pre tabIndex={0}>{JSON.stringify(event.detail, null, 2)}</pre>
            </>
          ) : (
            <p>
              This component has no output yet. Advance the test run to see its
              recorded input or result.
            </p>
          )}
        </div>
        <p className="dialog-provenance">
          Run {replay.id} · scripted model responses · n = {replay.sample_size}
        </p>
      </div>
    </dialog>
  );
}

function messageTerms(entry: ThreadEntry) {
  return entry.message?.term_sheets?.[0]?.terms ?? entry.message?.terms ?? {};
}
const stringList = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

function OfferHistory({ entries }: { entries: ThreadEntry[] }) {
  const points = entries.flatMap((entry) => {
    const value = messageTerms(entry).unit_price;
    return typeof value === "number"
      ? [{ step: entry.step, value, kind: entry.kind }]
      : [];
  });
  if (!points.length)
    return (
      <div className="chart-empty">
        The offer history starts when a quote arrives.
      </div>
    );
  const low = Math.min(...points.map((p) => p.value));
  const high = Math.max(...points.map((p) => p.value));
  const last = Math.max(...points.map((p) => p.step));
  const x = (step: number) =>
    65 + ((step - points[0].step) / Math.max(1, last - points[0].step)) * 505;
  const y = (value: number) => 22 + ((high - value) / (high - low || 1)) * 88;
  return (
    <div className="offer-history">
      <div className="chart-heading">
        <span className="eyebrow">How the offers evolve</span>
        <div>
          <span className="chart-ours">● Our proposal</span>
          <span className="chart-theirs">● Supplier offer</span>
        </div>
      </div>
      <svg
        viewBox="0 0 610 144"
        role="img"
        aria-label={`Unit prices over recorded steps, from ${price(low)} to ${price(high)}. Orange: our offers. Teal: supplier offers.`}
      >
        <title>Unit price by replay step</title>
        {[...new Set([high, low])].map((value, i) => (
          <g key={i}>
            <line
              x1={65}
              x2={585}
              y1={y(value)}
              y2={y(value)}
              className="chart-grid"
            />
            <text x={0} y={y(value) + 4} className="chart-axis">
              {price(value)}
            </text>
          </g>
        ))}
        {["supplier", "buyer"].map((kind) => {
          const series = points.filter((p) => p.kind === kind);
          return (
            <g key={kind} className={`price-series series-${kind}`}>
              <polyline
                points={series
                  .map((p) => `${x(p.step)},${y(p.value)}`)
                  .join(" ")}
                fill="none"
                strokeWidth={2}
              />
              {series.map((p) => (
                <circle key={p.step} cx={x(p.step)} cy={y(p.value)} r={3}>
                  <title>{`Step ${p.step}: ${price(p.value)}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
        <text x={65} y={137} className="chart-axis">
          Step {points[0].step}
        </text>
        <text x={570} y={137} className="chart-axis" textAnchor="end">
          Step {last}
        </text>
      </svg>
      <p>
        Unit price is one input. The decision engine compares complete offers at
        total cost.
      </p>
    </div>
  );
}

function ThreadRecord({ entry, sid }: { entry: ThreadEntry; sid: string }) {
  const { event, kind, message } = entry;
  const outcome = kind === "close" ? dealOutcome(entry.step) : null;
  const terms = messageTerms(entry);
  const result = event.detail.result as
    | {
        deal?: boolean;
        supplier_id?: string;
        c_deal?: number;
        terms?: Record<string, unknown>;
      }
    | undefined;
  const title =
    kind === "buyer"
      ? "Our proposal"
      : kind === "supplier"
        ? event.detail.quotes
          ? "Opening quote"
          : "Supplier reply"
        : kind === "analysis"
          ? "Analyst assessment"
          : kind === "decision"
            ? "Code decision"
            : result?.supplier_id === sid
              ? "This offer was accepted"
              : result?.deal
                ? "Another supplier was selected"
                : "Case closed without a deal";
  const claims = stringList(event.detail.claims);
  const asks = stringList(event.detail.asks);
  const checks = message?.claim_results ?? [];
  return (
    <article className={`thread-record record-${kind}`}>
      <div className="record-heading">
        <span className="record-icon">
          <Icon
            name={
              kind === "buyer" || kind === "supplier"
                ? "writer"
                : kind === "analysis"
                  ? "analyst"
                  : kind === "close"
                    ? "close"
                    : "negotiator"
            }
            size={16}
          />
        </span>
        <strong>{title}</strong>
        <span className="record-step">
          Step {String(entry.step).padStart(2, "0")}
        </span>
      </div>
      {message ? (
        <>
          <div className="email-direction">
            {kind === "buyer"
              ? "Hollerau Purchasing → Supplier"
              : `${supplierName(sid)} → Hollerau Purchasing`}
          </div>
          {message.subject && (
            <h4 className="email-subject">{message.subject}</h4>
          )}
          <p className="email-body">
            {message.body ?? message.text ?? "No email body recorded."}
          </p>
          {Object.keys(terms).length > 0 && (
            <div className="email-terms">
              {Object.entries(terms).map(([field, value]) => (
                <span key={field}>
                  <small>{field.replaceAll("_", " ")}</small>
                  <strong>
                    {field === "unit_price" && typeof value === "number"
                      ? price(value)
                      : typeof value === "object"
                        ? JSON.stringify(value)
                        : String(value)}
                  </strong>
                </span>
              ))}
            </div>
          )}
          {(message.term_sheets?.length ?? 0) > 1 && (
            <details className="extra-sheets">
              <summary>
                Alternative term sheets ({message.term_sheets!.length - 1})
              </summary>
              <pre>
                {JSON.stringify(message.term_sheets!.slice(1), null, 2)}
              </pre>
            </details>
          )}
          {checks.length > 0 && (
            <p className="claim-verification">
              <Icon name="check" size={13} />
              {
                checks.filter((check) => check.result === "verified").length
              } / {checks.length} claims verified by the simulator
            </p>
          )}
          {!!message.refs?.length && (
            <details className="email-refs">
              <summary>{message.refs.length} evidence references</summary>
              <ul>
                {message.refs.map((ref) => (
                  <li key={ref}>
                    <code>{ref}</code>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      ) : kind === "analysis" ? (
        <>
          <div className="reason-tags">
            <span>Mood: {String(event.detail.mood ?? "unrecorded")}</span>
            <span>Tactic: {String(event.detail.tactic ?? "unrecorded")}</span>
          </div>
          <p className="reason-copy">
            {String(event.detail.notes ?? "No analyst note recorded.")}
          </p>
          <p className="reason-footnote">
            Supplier asks: {asks.length ? asks.join(", ") : "none identified"} ·
            Scripted model assessment
          </p>
        </>
      ) : kind === "decision" ? (
        <>
          <div className="decision-prices">
            <span>
              Supplier offer
              <strong>
                {typeof event.detail.theirs === "number"
                  ? price(event.detail.theirs)
                  : "—"}
              </strong>
            </span>
            <Icon name="arrow" size={18} />
            <span>
              Policy proposal
              <strong>
                {typeof event.detail.ours === "number"
                  ? price(event.detail.ours)
                  : "—"}
              </strong>
            </span>
          </div>
          <p className="reason-copy">
            Policy state:{" "}
            <strong>
              {String(event.detail.state ?? "unrecorded").replaceAll("_", " ")}
            </strong>
            .{" "}
            {claims.length
              ? `Evidence selected: ${claims.map((claim) => claim.replaceAll("_", " ")).join(", ")}.`
              : "No new claim selected for this proposal."}
          </p>
          <p className="reason-footnote">
            Recorded policy decision. The following email carries the complete
            binding terms.
          </p>
        </>
      ) : (
        <>
          <p className="reason-copy">
            {result?.deal
              ? `${supplierName(result.supplier_id ?? null)} was selected at ${result.c_deal != null ? money(result.c_deal) : "the recorded"} total cost.`
              : "The close gate did not accept a standing sheet."}
          </p>
          <p className="reason-footnote">
            {outcome && (
              <>
                Agreed price:{" "}
                <strong>{price(outcome.unitPrice)} per unit</strong>.{" "}
                {outcome.savings >= 0 ? "Total savings" : "Cost increase"}:{" "}
                <strong>{price(Math.abs(outcome.savings))}</strong> over{" "}
                {outcome.months} months versus opening total cost.{" "}
              </>
            )}
            The gate compares valid standing sheets across suppliers, including
            all terms.
          </p>
        </>
      )}
    </article>
  );
}

export function ThreadInspector({
  sid,
  index,
  playing,
  onToggle,
  onClose,
  onJump,
}: {
  sid: string;
  index: number;
  playing: boolean;
  onToggle: () => void;
  onClose: () => void;
  onJump: (step: number) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { following, onScroll, follow } = useAutoFollow(dialog, index, sid);
  const entries = threadEntries(index, sid);
  const allEntries = threadEntries(events.length, sid);
  const previous = [...entries].reverse().find((entry) => entry.step < index);
  const next = allEntries.find((entry) => entry.step > index);
  const state = events[index - 1]?.suppliers[sid];
  const closed = events
    .slice(0, index)
    .some((event) => event.stage === "close");
  const emails = entries.filter((entry) => entry.message);
  const offers = emails.filter((entry) => entry.kind === "supplier");
  const opening = offers[0] ? messageTerms(offers[0]).unit_price : undefined;
  useEffect(() => {
    const element = dialog.current;
    const focused = document.activeElement as HTMLElement | null;
    element?.showModal();
    return () => {
      element?.close();
      focused?.focus();
    };
  }, []);
  const advance = (step: number) => {
    follow();
    onJump(step);
  };
  return (
    <dialog
      ref={dialog}
      className="thread-dialog"
      onScroll={onScroll}
      aria-labelledby="thread-title"
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <header className="thread-dialog-header">
        <div>
          <span className="eyebrow">
            Supplier conversation · live test playback
          </span>
          <h2 id="thread-title">{supplierName(sid)}</h2>
          <p>
            {closed
              ? state?.status === "accepted"
                ? "Accepted · case closed"
                : "Not selected · case closed"
              : state
                ? "Negotiation in progress"
                : "Waiting for opening quote"}
            <span>·</span>
            {emails.length} emails<span>·</span>Step {index} of {events.length}
          </p>
        </div>
        <button
          className="icon-button"
          aria-label="Close supplier conversation"
          onClick={onClose}
        >
          <Icon name="x" />
        </button>
      </header>
      <div className="thread-dialog-body">
        <div className="thread-metrics">
          <div>
            <span>Opening unit price</span>
            <strong>
              {typeof opening === "number" ? price(opening) : "—"}
            </strong>
          </div>
          <div>
            <span>Current supplier offer</span>
            <strong>{state?.price != null ? price(state.price) : "—"}</strong>
          </div>
          <div>
            <span>Standing total cost</span>
            <strong>{state?.cost != null ? money(state.cost) : "—"}</strong>
          </div>
        </div>
        <OfferHistory entries={entries} />
        <div className="transcript-heading">
          <h3>Conversation & decision trail</h3>
          <span>Through step {index}</span>
        </div>
        <p className="transcript-note">
          Original test emails and recorded analyst / policy notes. Model
          responses are scripted fixtures; future steps stay hidden.
        </p>
        {!entries.length && (
          <div className="thread-empty">
            <Icon name="writer" size={30} />
            <h3>No emails yet</h3>
            <p>
              Advance to the opening quote to follow this supplier's
              negotiation.
            </p>
          </div>
        )}
        <div className="thread-transcript">
          {entries.map((entry) => (
            <ThreadRecord
              key={`${entry.step}-${entry.kind}`}
              entry={entry}
              sid={sid}
            />
          ))}
        </div>
      </div>
      <footer className="thread-dialog-footer">
        <button
          className="thread-nav"
          disabled={!previous}
          onClick={() => previous && advance(previous.step)}
        >
          <Icon name="back" size={16} /> Previous event
        </button>
        <button className="thread-play" onClick={onToggle}>
          <Icon name={playing ? "pause" : "play"} size={15} />
          {playing
            ? "Pause thread"
            : index === events.length
              ? "Replay thread"
              : "Play thread"}
        </button>
        {!following && (
          <button className="thread-nav" onClick={follow}>
            Latest ↓
          </button>
        )}
        <button
          className="thread-nav next-thread"
          disabled={!next}
          onClick={() => next && advance(next.step)}
        >
          Next thread event <Icon name="arrow" size={16} />
        </button>
      </footer>
    </dialog>
  );
}
