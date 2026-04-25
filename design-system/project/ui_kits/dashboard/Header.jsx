/* global React */

function Header({ portfolio, generated, commit }) {
  return (
    <header className="dh-header">
      <div className="dh-brand">
        <span className="dh-wm">rikdom</span><span className="dh-dot"></span>
      </div>
      <div className="dh-crumbs">
        <span className="dh-crumb">{portfolio}</span>
        <span className="dh-sep">·</span>
        <span className="dh-crumb">portfolio</span>
      </div>
      <div className="dh-meta">
        <div><span className="dh-meta-k">generated</span> <span className="dh-meta-v">{generated}</span></div>
        <div><span className="dh-meta-k">built from</span> <span className="dh-meta-v mono">{commit}</span></div>
        <div><span className="dh-meta-k">schema</span> <span className="dh-meta-v mono">v0.3</span></div>
      </div>
    </header>
  );
}

window.Header = Header;
