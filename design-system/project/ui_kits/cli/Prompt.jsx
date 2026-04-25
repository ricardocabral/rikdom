/* global React */
const { useState, useEffect, useRef } = React;

function Prompt({ cwd = "~/portfolio", onSubmit, hint }) {
  const [value, setValue] = useState("");
  const [history, setHistory] = useState([]);
  const [hIdx, setHIdx] = useState(-1);
  const inputRef = useRef(null);

  useEffect(() => {
    const focus = () => inputRef.current && inputRef.current.focus();
    focus();
    document.addEventListener("click", focus);
    return () => document.removeEventListener("click", focus);
  }, []);

  const submit = (e) => {
    e.preventDefault();
    const v = value.trim();
    if (!v) return;
    setHistory([v, ...history]);
    setHIdx(-1);
    setValue("");
    onSubmit(v);
  };

  const onKey = (e) => {
    if (e.key === "ArrowUp" && history.length) {
      const next = Math.min(history.length - 1, hIdx + 1);
      setHIdx(next);
      setValue(history[next] || "");
      e.preventDefault();
    } else if (e.key === "ArrowDown") {
      const next = Math.max(-1, hIdx - 1);
      setHIdx(next);
      setValue(next === -1 ? "" : history[next] || "");
      e.preventDefault();
    }
  };

  return (
    <form className="prompt-form" onSubmit={submit}>
      <div className="line prompt-live">
        <span className="prompt-user">you</span>
        <span className="prompt-at">@</span>
        <span className="prompt-host">rikdom</span>
        <span className="prompt-sep"> · </span>
        <span className="prompt-cwd">{cwd}</span>
        <span className="prompt-caret"> ❯ </span>
        <input
          ref={inputRef}
          className="prompt-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKey}
          spellCheck={false}
          autoComplete="off"
        />
      </div>
      {hint && !value && (
        <div className="prompt-hint">{hint}</div>
      )}
    </form>
  );
}

window.Prompt = Prompt;
