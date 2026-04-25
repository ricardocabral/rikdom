/* global React */

function Tree({ items }) {
  // items: [{label, children?, meta?}]
  return (
    <div className="tree">
      {items.map((it, i) => (
        <TreeNode key={i} node={it} prefix="" last={i === items.length - 1} />
      ))}
    </div>
  );
}

function TreeNode({ node, prefix, last }) {
  const branch = last ? "└─ " : "├─ ";
  const childPrefix = prefix + (last ? "   " : "│  ");
  return (
    <>
      <div className="tree-line">
        <span className="tree-prefix">{prefix}{branch}</span>
        <span className="tree-label">{node.label}</span>
        {node.meta && <span className="tree-meta">  {node.meta}</span>}
      </div>
      {node.children &&
        node.children.map((c, i) => (
          <TreeNode
            key={i}
            node={c}
            prefix={childPrefix}
            last={i === node.children.length - 1}
          />
        ))}
    </>
  );
}

function Schema({ json }) {
  const text = typeof json === "string" ? json : JSON.stringify(json, null, 2);
  return (
    <pre className="schema">
      <code>{colorizeJson(text)}</code>
    </pre>
  );
}

function colorizeJson(text) {
  // minimal JSON token colorizer for display only
  const parts = [];
  const regex = /("(?:[^"\\]|\\.)*"\s*:|"(?:[^"\\]|\\.)*"|\b-?\d+(?:\.\d+)?\b|\btrue\b|\bfalse\b|\bnull\b)/g;
  let lastIndex = 0;
  let m;
  let key = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index));
    const tok = m[0];
    let cls = "j-val";
    if (/^".*":\s*$/.test(tok)) cls = "j-key";
    else if (/^".*"$/.test(tok)) cls = "j-str";
    else if (/^(true|false)$/.test(tok)) cls = "j-bool";
    else if (tok === "null") cls = "j-null";
    else if (/^-?\d/.test(tok)) cls = "j-num";
    parts.push(<span key={key++} className={cls}>{tok}</span>);
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

function Table({ cols, rows, align = [] }) {
  return (
    <div className="otable">
      <div className="otable-head">
        {cols.map((c, i) => (
          <div key={i} className="otable-cell" style={{ textAlign: align[i] || "left" }}>{c}</div>
        ))}
      </div>
      {rows.map((r, i) => (
        <div key={i} className="otable-row">
          {r.map((cell, j) => (
            <div key={j} className="otable-cell" style={{ textAlign: align[j] || "left" }}>{cell}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

window.Tree = Tree;
window.Schema = Schema;
window.Table = Table;
