"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi, useTheme } from "@/lib/hooks";

const NAV = [
  { href: "/", label: "Team pulse", icon: "pulse" },
  { href: "/status", label: "Status", icon: "status" },
  { href: "/expertise", label: "Expertise", icon: "expertise" },
  { href: "/knowledge", label: "Knowledge", icon: "knowledge" },
  { href: "/knowledge/gaps", label: "Gap analytics", icon: "gaps" },
  { href: "/ask", label: "Ask Hive", icon: "ask" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;

function Icon({ name }: { name: string }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (name) {
    case "pulse":
      return (
        <svg {...common}>
          <path d="M1.5 8.5h3l1.5-4 2.5 8 2-4h4" />
        </svg>
      );
    case "status":
      return (
        <svg {...common}>
          <rect x="2" y="2.5" width="12" height="11" rx="2" />
          <path d="M5 6.5h6M5 9.5h4" />
        </svg>
      );
    case "expertise":
      return (
        <svg {...common}>
          <circle cx="4" cy="4" r="2" />
          <circle cx="12" cy="7" r="2" />
          <circle cx="5" cy="12" r="2" />
          <path d="M5.8 5.2 10.2 6.3M5.3 10.2 10.8 8.6" />
        </svg>
      );
    case "knowledge":
      return (
        <svg {...common}>
          <path d="M3 3.5h4.5A1.5 1.5 0 0 1 9 5v8a1.2 1.2 0 0 0-1.2-1.2H3z" />
          <path d="M13 3.5H8.5A1.5 1.5 0 0 0 7 5v8a1.2 1.2 0 0 1 1.2-1.2H13z" />
        </svg>
      );
    case "gaps":
      return (
        <svg {...common}>
          <path d="M2 13.5V9m4 4.5V4m4 9.5v-6m4 6V6" />
        </svg>
      );
    case "ask":
      return (
        <svg {...common}>
          <path d="M14 9.5A3.5 3.5 0 0 1 10.5 13H6l-3.5 2.2V5.5A2.5 2.5 0 0 1 5 3h6.5A2.5 2.5 0 0 1 14 5.5z" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="2.2" />
          <path d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1" />
        </svg>
      );
  }
}

function HiveMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden>
      <path
        d="M12 2.6 20.4 7.3v9.4L12 21.4 3.6 16.7V7.3z"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button
      onClick={toggle}
      title="Toggle light and dark"
      aria-label="Toggle light and dark"
      className="rounded-lg border border-hairline p-1.5 text-ink-secondary transition-colors hover:bg-surface-2 hover:text-ink"
    >
      {theme === "light" ? (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          <path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          <circle cx="8" cy="8" r="3" />
          <path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3.1 3.1l1.1 1.1M11.8 11.8l1.1 1.1M12.9 3.1l-1.1 1.1M4.2 11.8l-1.1 1.1" />
        </svg>
      )}
    </button>
  );
}

function ProviderBadge() {
  const { data } = useApi(() => api.health(), []);
  if (!data) return null;
  const offline = data.llm_provider === "stub";
  return (
    <span
      title={
        offline
          ? "No LLM configured: answers are extractive evidence lists, not prose."
          : `LLM: ${data.llm_provider} · embeddings: ${data.embedding_provider}`
      }
      className="hidden items-center gap-1.5 rounded-full border border-hairline px-2 py-0.5 text-xs text-ink-muted sm:inline-flex"
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${offline ? "bg-warning" : "bg-good"}`}
        aria-hidden
      />
      {offline ? "offline providers" : data.llm_provider}
    </span>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // Longest matching prefix wins, so /knowledge/gaps does not also light up
  // /knowledge.
  const activeHref = NAV.map((item) => item.href)
    .filter((href) =>
      href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`),
    )
    .sort((a, b) => b.length - a.length)[0];
  const isActive = (href: string) => href === activeHref;

  return (
    <div className="flex min-h-screen">
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-60 shrink-0 border-r border-hairline bg-surface-1 transition-transform lg:static lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-14 items-center gap-2 border-b border-hairline px-4">
          <HiveMark />
          <span className="text-sm font-semibold tracking-tight text-ink">Hive</span>
          <span className="ml-auto text-[10px] uppercase tracking-wider text-ink-muted">
            read-only
          </span>
        </div>
        <nav className="p-2">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className={`mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                isActive(item.href)
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-ink-secondary hover:bg-surface-2 hover:text-ink"
              }`}
            >
              <Icon name={item.icon} />
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-hairline p-4">
          <p className="text-xs leading-relaxed text-ink-muted">
            Hive never writes to your tools. Every answer cites its source.
          </p>
        </div>
      </aside>

      {open ? (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setOpen(false)}
          aria-hidden
        />
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-hairline bg-surface-0/85 px-4 backdrop-blur">
          <button
            onClick={() => setOpen((value) => !value)}
            className="rounded-lg border border-hairline p-1.5 text-ink-secondary lg:hidden"
            aria-label="Toggle navigation"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" stroke="currentColor" strokeWidth="1.5" aria-hidden>
              <path d="M2 4h12M2 8h12M2 12h12" />
            </svg>
          </button>
          <p className="truncate text-sm text-ink-secondary">
            {NAV.find((item) => isActive(item.href))?.label ?? "Hive"}
          </p>
          <div className="ml-auto flex items-center gap-2">
            <ProviderBadge />
            <ThemeToggle />
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
