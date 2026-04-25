/* global React */

function HoldingsTable({ groups }) {
  return (
    <section className="dh-section">
      <div className="dh-section-title">
        <span className="dh-eyebrow">Holdings</span>
      </div>
      <table className="dh-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Name</th>
            <th style={{ textAlign: "left" }}>Class</th>
            <th style={{ textAlign: "right" }}>Qty</th>
            <th style={{ textAlign: "right" }}>Value (NOK)</th>
            <th style={{ textAlign: "right" }}>Δ 30d</th>
            <th style={{ textAlign: "right" }}>Share</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g, gi) => (
            <React.Fragment key={gi}>
              <tr className="dh-group-row">
                <td colSpan={6}>{g.label} <span className="dh-group-count">· {g.rows.length}</span></td>
              </tr>
              {g.rows.map((r, ri) => (
                <tr key={ri}>
                  <td>{r.name}<div className="dh-row-sub">{r.sub}</div></td>
                  <td className="mono dh-row-class">{r.cls}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{r.qty}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{r.value}</td>
                  <td className="mono" style={{ textAlign: "right", color: r.delta >= 0 ? "var(--pos)" : r.delta < 0 ? "var(--neg)" : "var(--fg-3)" }}>
                    {r.delta === null ? "—" : (r.delta >= 0 ? "+" : "−") + Math.abs(r.delta).toFixed(1) + "%"}
                  </td>
                  <td className="mono" style={{ textAlign: "right", color: "var(--fg-2)" }}>{r.share}%</td>
                </tr>
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </section>
  );
}

window.HoldingsTable = HoldingsTable;
