/* global React */

function Allocation({ slices }) {
  const total = slices.reduce((a, b) => a + b.pct, 0);
  return (
    <section className="dh-section">
      <div className="dh-section-title">
        <span className="dh-eyebrow">Allocation</span>
      </div>
      <div className="dh-alloc-bar">
        {slices.map((s, i) => (
          <div key={i} className="dh-alloc-seg" style={{ flex: s.pct, background: s.color }} title={`${s.label} ${s.pct}%`}></div>
        ))}
      </div>
      <div className="dh-alloc-legend">
        {slices.map((s, i) => (
          <div key={i} className="dh-alloc-item">
            <span className="dh-alloc-swatch" style={{ background: s.color }}></span>
            <span className="dh-alloc-label">{s.label}</span>
            <span className="dh-alloc-pct">{s.pct}%</span>
          </div>
        ))}
      </div>
    </section>
  );
}

window.Allocation = Allocation;
