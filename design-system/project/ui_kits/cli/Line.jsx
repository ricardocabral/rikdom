/* global React */

function PromptLine({ cwd = "~/portfolio", cmd }) {
  return (
    <div className="line">
      <span className="prompt-user">you</span>
      <span className="prompt-at">@</span>
      <span className="prompt-host">rikdom</span>
      <span className="prompt-sep"> · </span>
      <span className="prompt-cwd">{cwd}</span>
      <span className="prompt-caret"> ❯ </span>
      <span className="prompt-cmd">{cmd}</span>
    </div>
  );
}

function OutLine({ children, tone }) {
  const cls = tone ? `line out out-${tone}` : "line out";
  return <div className={cls}>{children}</div>;
}

function Blank() {
  return <div className="line">&nbsp;</div>;
}

function Note({ children }) {
  return (
    <div className="line out note">
      <span className="note-mark">·</span> {children}
    </div>
  );
}

window.PromptLine = PromptLine;
window.OutLine = OutLine;
window.Blank = Blank;
window.Note = Note;
