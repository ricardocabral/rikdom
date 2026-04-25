/* global React */

function Summary({ total, delta30, delta1y, holdings, classes, asOf }) {
  const pos = delta30 >= 0;
  return (
    <section className="dh-summary">
      <div className="dh-summary-main">
        <div className="dh-eyebrow">Total value · as of {asOf}</div>
        <div className="dh-hero">
          {formatNum(total)} <span className="dh-hero-unit">NOK</span>
        </div>
        <div className="dh-sub">
          <span className={pos ? "dh-delta-pos" : "dh-delta-neg"}>
            {pos ? "+" : "−"}{formatNum(Math.abs(delta30))} NOK
          </span>
          <span className="dh-sub-sep">·</span>
          <span className="dh-sub-muted">30 days</span>
          <span className="dh-sub-sep">·</span>
          <span className={delta1y >= 0 ? "dh-delta-pos" : "dh-delta-neg"}>
            {delta1y >= 0 ? "+" : "−"}{Math.abs(delta1y).toFixed(1)}%
          </span>
          <span className="dh-sub-muted"> 1y</span>
        </div>
      </div>
      <div className="dh-summary-side">
        <div className="dh-stat">
          <div className="dh-stat-k">Holdings</div>
          <div className="dh-stat-v">{holdings}</div>
        </div>
        <div className="dh-stat">
          <div className="dh-stat-k">Asset classes</div>
          <div className="dh-stat-v">{classes}</div>
        </div>
      </div>
    </section>
  );
}

function formatNum(n) {
  return Math.round(n).toLocaleString("en-US").replace(/,/g, "\u202F");
}

window.Summary = Summary;
