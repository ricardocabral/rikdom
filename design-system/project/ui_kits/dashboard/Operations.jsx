/* global React */

function Operations({ items }) {
  return (
    <section className="dh-section">
      <div className="dh-section-title">
        <span className="dh-eyebrow">Recurring operations</span>
      </div>
      <div className="dh-ops">
        {items.map((op, i) => (
          <div key={i} className={"dh-op dh-op-" + op.status}>
            <div className="dh-op-title">{op.name}</div>
            <div className="dh-op-meta">
              <span>last · <span className="mono">{op.last}</span></span>
              <span className="dh-sub-sep">·</span>
              <span>next · <span className="mono">{op.next}</span></span>
            </div>
            <div className="dh-op-status">{op.statusLabel}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

window.Operations = Operations;
