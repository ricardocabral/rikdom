/* global React */
const { useState, useRef, useEffect } = React;

function Terminal({ children, title = "~/portfolio — rikdom" }) {
  const scrollerRef = useRef(null);
  useEffect(() => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });
  return (
    <div className="term">
      <div className="term-chrome">
        <div className="term-dots">
          <span style={{ background: "#B8AE9E" }} />
          <span style={{ background: "#B8AE9E" }} />
          <span style={{ background: "#B8AE9E" }} />
        </div>
        <div className="term-title">{title}</div>
        <div style={{ width: 48 }} />
      </div>
      <div className="term-body" ref={scrollerRef}>
        {children}
      </div>
    </div>
  );
}

window.Terminal = Terminal;
