"use client";

import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section
      className={`rounded-xl border border-hairline bg-surface-1 ${padded ? "p-5" : ""} ${className}`}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-4 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
        {hint ? <p className="mt-0.5 text-xs text-ink-muted">{hint}</p> : null}
      </div>
      {action}
    </header>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-ink-secondary">{subtitle}</p> : null}
      </div>
      {action}
    </header>
  );
}

export function Button({
  children,
  onClick,
  variant = "ghost",
  size = "md",
  type = "button",
  disabled,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "ghost" | "solid" | "quiet";
  size?: "sm" | "md";
  type?: "button" | "submit";
  disabled?: boolean;
  title?: string;
}) {
  const base =
    "inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-45 disabled:cursor-not-allowed";
  const sizes = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm";
  const variants = {
    solid: "bg-accent text-surface-0 hover:opacity-90",
    ghost: "border border-hairline text-ink-secondary hover:bg-surface-2 hover:text-ink",
    quiet: "text-ink-muted hover:text-ink hover:bg-surface-2",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${base} ${sizes} ${variants}`}
    >
      {children}
    </button>
  );
}

export function Chip({
  children,
  tone = "neutral",
  onClick,
  active,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent";
  onClick?: () => void;
  active?: boolean;
}) {
  const tones = {
    neutral: "border-hairline text-ink-secondary",
    accent: "border-transparent bg-accent-soft text-accent",
  }[tone];
  const interactive = onClick
    ? "cursor-pointer hover:bg-surface-2"
    : "";
  const selected = active ? "border-accent text-accent bg-accent-soft" : tones;
  return (
    <span
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") onClick();
            }
          : undefined
      }
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${selected} ${interactive}`}
    >
      {children}
    </span>
  );
}

const SEVERITY_STYLE: Record<string, { dot: string; label: string }> = {
  error: { dot: "bg-critical", label: "Error" },
  warn: { dot: "bg-warning", label: "Warning" },
  info: { dot: "bg-series-1", label: "Info" },
};

/** Status is never colour-alone: every severity ships a dot plus its word. */
export function SeverityBadge({ severity }: { severity: string }) {
  const style = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.info;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-secondary">
      <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} aria-hidden />
      {style.label}
    </span>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton rounded ${className}`} />;
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-hairline px-6 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint ? <p className="max-w-md text-xs text-ink-muted">{hint}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({
  message,
  detail,
  onRetry,
}: {
  message: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-lg border border-hairline bg-surface-2 px-4 py-4">
      <div className="flex items-start gap-2">
        <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-critical" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">{message}</p>
          {detail ? <p className="mt-1 break-words text-xs text-ink-muted">{detail}</p> : null}
          <p className="mt-2 text-xs text-ink-muted">
            Is the API running? <code className="text-ink-secondary">uvicorn api.main:app</code>
          </p>
        </div>
        {onRetry ? (
          <Button size="sm" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function Metric({
  label,
  value,
  hint,
  unavailable,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  unavailable?: string;
}) {
  return (
    <div className="rounded-xl border border-hairline bg-surface-1 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      {unavailable ? (
        <>
          <p className="mt-2 text-2xl font-semibold text-ink-muted">—</p>
          <p className="mt-1 text-xs text-ink-muted">{unavailable}</p>
        </>
      ) : (
        <>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-ink">{value}</p>
          {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
        </>
      )}
    </div>
  );
}

export function Avatar({ name, tint, size = 32 }: { name: string; tint: string; size?: number }) {
  return (
    <span
      aria-hidden
      style={{ background: tint, width: size, height: size, fontSize: size * 0.38 }}
      className="flex shrink-0 items-center justify-center rounded-full font-semibold text-white/95"
    >
      {name}
    </span>
  );
}
