import { useEffect, useRef, useState, type RefObject } from "react";
import { Icon } from "./Schematic";
import { agents } from "./steps";
import {
  events,
  money,
  price,
  replay,
  supplierName,
  threadEntries,
  dealOutcome,
  type ThreadEntry,
} from "./replay";

// Follow new records, but let someone scroll back to read without being pulled down.
export function useAutoFollow(
  ref: RefObject<HTMLElement | null>,
  position: number,
  context: string,
) {
  const [following, setFollowing] = useState(true);
  const previous = useRef({ position, context });
  useEffect(() => {
    const reset =
      context !== previous.current.context ||
      position < previous.current.position;
    previous.current = { position, context };
    if (reset) setFollowing(true);
    if (!following && !reset) return;
    const frame = requestAnimationFrame(() => {
      const element = ref.current;
      if (element) element.scrollTop = element.scrollHeight;
    });
    return () => cancelAnimationFrame(frame);
  }, [position, context, following, ref]);
  const onScroll = () => {
    const element = ref.current;
    if (element)
      setFollowing(
        element.scrollHeight - element.scrollTop - element.clientHeight < 85,
      );
  };
  return { following, onScroll, follow: () => setFollowing(true) };
}

function CompactRecord({
  entry,
  previousPrice,
}: {
  entry: ThreadEntry;
  previousPrice?: number;
}) {
  const { kind, message, event } = entry;
  const outcome = kind === "close" ? dealOutcome(entry.step) : null;
  const terms = message?.term_sheets?.[0]?.terms ?? message?.terms ?? {};
  const unitPrice =
    typeof terms.unit_price === "number" ? terms.unit_price : undefined;
  const result = event.detail.result as
    | { supplier_id?: string; c_deal?: number; deal?: boolean }
    | undefined;
  const body = message?.body ?? message?.text ?? "";
  const excerpt =
    body
      .split("\n\n")
      .find((paragraph) => paragraph.startsWith("On this basis")) ?? body;
  const label =
    kind === "buyer"
      ? "Our proposal"
      : kind === "supplier"
        ? event.detail.quotes
          ? "Opening quote"
          : "Supplier reply"
        : kind === "analysis"
          ? "Analyst"
          : kind === "decision"
            ? "Decision engine"
            : "Case closed";
  const changed =
    unitPrice != null && previousPrice != null
      ? unitPrice - previousPrice
      : null;
  const [expanded, setExpanded] = useState(false);
  return (
    <li className={`live-record live-${kind}`}>
      <span className="thread-line-dot">
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
          size={12}
        />
      </span>
      <div className="live-record-card">
        <div className="live-record-heading">
          <strong>{label}</strong>
          <small>{String(entry.step).padStart(2, "0")}</small>
        </div>
        {message ? (
          <>
            {unitPrice != null && (
              <div className="live-offer">
                <strong>
                  {price(unitPrice)}
                  <small> / unit</small>
                </strong>
                {changed != null && Math.abs(changed) > 0.001 && (
                  <span className={changed < 0 ? "price-down" : "price-up"}>
                    {changed < 0 ? "↓" : "↑"} {price(Math.abs(changed))}
                  </span>
                )}
              </div>
            )}
            <p className={`live-email ${expanded ? "expanded" : ""}`}>
              {expanded ? body : excerpt}
            </p>
            {!!Object.keys(terms).filter((key) => key !== "unit_price")
              .length && (
              <div className="live-terms">
                {Object.entries(terms)
                  .filter(([key]) => key !== "unit_price")
                  .map(([key, value]) => (
                    <span key={key}>
                      {key.replaceAll("_", " ")}: {String(value)}
                    </span>
                  ))}
              </div>
            )}
            <button
              className="email-toggle"
              aria-expanded={expanded}
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "Collapse email" : "Read email"}{" "}
              <Icon name={expanded ? "back" : "arrow"} size={11} />
            </button>
          </>
        ) : kind === "analysis" ? (
          <p className="live-reason">
            <span className="tactic-pill">
              {String(event.detail.tactic ?? "steady")}
            </span>
            {String(event.detail.notes ?? "Reply interpreted.")}
          </p>
        ) : kind === "decision" ? (
          <p className="live-reason">
            {typeof event.detail.ours === "number" ? (
              <>
                Proposal checked at <strong>{price(event.detail.ours)}</strong>.
              </>
            ) : (
              "Terms checked."
            )}{" "}
            <span>
              {Array.isArray(event.detail.claims) && event.detail.claims.length
                ? `Evidence: ${event.detail.claims.join(", ").replaceAll("_", " ")}.`
                : "No new claim needed."}
            </span>
          </p>
        ) : (
          <p className="live-reason">
            {result?.deal ? (
              <>
                <strong>{supplierName(result.supplier_id ?? null)}</strong>{" "}
                selected
                {result.c_deal != null
                  ? ` at ${money(result.c_deal)} total cost`
                  : ""}
                .
                {outcome && (
                  <span>
                    Agreed at <strong>{price(outcome.unitPrice)} / unit</strong>
                    . {price(Math.abs(outcome.savings))}{" "}
                    {outcome.savings >= 0 ? "saved" : "cost increase"} over{" "}
                    {outcome.months} months versus opening total cost.
                  </span>
                )}
              </>
            ) : (
              "No standing offer accepted."
            )}
          </p>
        )}
      </div>
    </li>
  );
}

export function LiveThreadLine({
  sid,
  index,
  playing,
}: {
  sid: string;
  index: number;
  playing: boolean;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const entries = threadEntries(index, sid);
  const { following, onScroll, follow } = useAutoFollow(scroll, index, sid);
  const event = events[index - 1];
  const complete = index === events.length;
  const previousPrices: Partial<Record<ThreadEntry["kind"], number>> = {};
  return (
    <div className="live-thread">
      <div className="live-feed-label">
        <span>
          <span className={`status-dot ${playing ? "live-pulse" : ""}`} />
          {playing
            ? "Live thread"
            : complete
              ? "Thread complete"
              : "Thread timeline"}
        </span>
        <span>{entries.filter((entry) => entry.message).length} emails</span>
      </div>
      <div
        className="live-thread-scroll"
        ref={scroll}
        onScroll={onScroll}
        tabIndex={0}
        aria-label={`Live conversation with ${supplierName(sid)}`}
      >
        {!entries.length && (
          <div className="live-thread-empty">
            <Icon name="writer" size={27} />
            <strong>
              {playing
                ? "Preparing the opening…"
                : "Watch the negotiation unfold"}
            </strong>
            <p>Messages, proposals and replies appear here as the test runs.</p>
            <span>
              {replay.case.round_limit} rounds · {replay.suppliers.length}{" "}
              suppliers
            </span>
          </div>
        )}
        <ol
          className="live-thread-line"
          aria-live="polite"
          aria-relevant="additions"
        >
          {entries.map((entry) => {
            const terms =
              entry.message?.term_sheets?.[0]?.terms ??
              entry.message?.terms ??
              {};
            const previousPrice = previousPrices[entry.kind];
            if (typeof terms.unit_price === "number")
              previousPrices[entry.kind] = terms.unit_price;
            return (
              <CompactRecord
                key={`${sid}-${entry.step}`}
                entry={entry}
                previousPrice={previousPrice}
              />
            );
          })}
        </ol>
        {playing && (
          <div className="thread-typing">
            <span />
            <span />
            <span />
            <p>
              {event?.supplier && event.supplier !== sid
                ? "The team is working on the other thread"
                : event
                  ? `${agents[event.stage].name} is working`
                  : "Research is starting"}
              …
            </p>
          </div>
        )}
      </div>
      {!following && (
        <button className="follow-latest" onClick={follow}>
          Jump to latest <span>↓</span>
        </button>
      )}
    </div>
  );
}

export function supplierLabel(sid: string) {
  const name =
    replay.suppliers.find((supplier) => supplier.id === sid)?.name ?? sid;
  const words = name.split(" ");
  return words.length > 2 ? words[words.length - 2] : name;
}
