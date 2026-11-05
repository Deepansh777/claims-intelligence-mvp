import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
}

export function Modal({ children, onClose, large }: { children: ReactNode; onClose: () => void; large?: boolean }) {
  useEscape(onClose);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={"modal" + (large ? " lg" : "")} role="dialog" aria-modal="true">
        {children}
      </div>
    </div>
  );
}

export function Drawer({
  title,
  sub,
  children,
  onClose,
}: {
  title: string;
  sub: string;
  children: ReactNode;
  onClose: () => void;
}) {
  useEscape(onClose);
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="drawer-head">
          <div>
            <h2>{title}</h2>
            <div className="drawer-sub">{sub}</div>
          </div>
          <button className="drawer-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </>
  );
}

export function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1300);
  };
  return (
    <div className="code-wrap">
      <button className={"code-copy" + (copied ? " is-done" : "")} type="button" onClick={copy}>
        <Icon name={copied ? "check" : "copy"} />
        {copied ? "Copied" : "Copy"}
      </button>
      <pre className="code-block">{code}</pre>
    </div>
  );
}
