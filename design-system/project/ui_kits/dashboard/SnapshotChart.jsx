/* global React */

function SnapshotChart({ points }) {
  const W = 920, H = 220, PAD_L = 52, PAD_R = 16, PAD_T = 16, PAD_B = 28;

  if (!points || points.length === 0) {
    return (
      <section className="dh-section">
        <div className="dh-section-title">
          <span className="dh-eyebrow">Snapshots · last 12 months</span>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="dh-chart" width="100%" preserveAspectRatio="xMidYMid meet">
          <text x={W / 2} y={H / 2} fontSize="12" fill="#8A8070" textAnchor="middle" fontFamily="JetBrains Mono, monospace">
            no snapshots yet
          </text>
        </svg>
      </section>
    );
  }

  const xs = points.map((_, i) => i);
  const ys = points.map(p => p.v);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const yRange = yMax - yMin || 1;
  const xDenom = xs.length > 1 ? xs.length - 1 : 1;
  const sx = (i) => xs.length > 1
    ? PAD_L + (i / xDenom) * (W - PAD_L - PAD_R)
    : (PAD_L + (W - PAD_R)) / 2;
  const sy = (v) => PAD_T + (1 - (v - yMin) / yRange) * (H - PAD_T - PAD_B);
  const d = points.map((p, i) => (i === 0 ? "M" : "L") + sx(i) + " " + sy(p.v)).join(" ");
  const area = d + ` L ${sx(points.length - 1)} ${H - PAD_B} L ${sx(0)} ${H - PAD_B} Z`;

  const gridVals = 4;
  const gridLines = Array.from({ length: gridVals + 1 }, (_, i) => {
    const v = yMin + (yRange * i) / gridVals;
    return { v, y: sy(v) };
  });

  return (
    <section className="dh-section">
      <div className="dh-section-title">
        <span className="dh-eyebrow">Snapshots · last 12 months</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="dh-chart" width="100%" preserveAspectRatio="xMidYMid meet">
        {gridLines.map((g, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={W - PAD_R} y1={g.y} y2={g.y} stroke="#D9D1C1" strokeWidth="1" />
            <text x={PAD_L - 8} y={g.y + 4} fontSize="10" fill="#8A8070" textAnchor="end" fontFamily="JetBrains Mono, monospace">
              {Math.round(g.v / 1000)}k
            </text>
          </g>
        ))}
        <path d={area} fill="#2C4A6B" fillOpacity="0.08" />
        <path d={d} fill="none" stroke="#2C4A6B" strokeWidth="1.5" />
        {points.map((p, i) => (
          <circle key={i} cx={sx(i)} cy={sy(p.v)} r="2.5" fill="#2C4A6B" />
        ))}
        {points.map((p, i) => (
          (i % 2 === 0) && (
            <text key={"l"+i} x={sx(i)} y={H - 8} fontSize="10" fill="#8A8070" textAnchor="middle" fontFamily="JetBrains Mono, monospace">
              {p.label}
            </text>
          )
        ))}
      </svg>
    </section>
  );
}

window.SnapshotChart = SnapshotChart;
