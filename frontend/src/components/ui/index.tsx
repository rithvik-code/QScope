/**
 * The interface kit.
 *
 * Everything here is deliberately plain: the instrument look comes from the
 * palette tokens and the motion primitives, not from a control library.  The one
 * thing that is not plain is `Provenance`, which exists so that every result can
 * say what produced it — engine, representation, exactness, seed, shots, error
 * model, timing and memory — wherever it is shown.
 */

import { useState, type ChangeEvent, type ReactNode } from "react";
import { MeterBar, PulseDot } from "../motion";

// -------------------------------------------------------------------- Panel

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  dense = false,
  accent,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  dense?: boolean;
  accent?: string;
}) {
  return (
    <section className={`panel ${dense ? "p-3" : "p-4"} ${className ?? ""}`} style={accent ? { borderColor: accent } : undefined}>
      {(title || actions) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="truncate text-[13px] font-semibold tracking-tight text-[var(--c-text)]">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[11px] leading-snug text-[var(--c-muted)]">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-2 flex items-baseline gap-2">
      <h3 className="label-xs">{children}</h3>
      {hint && <span className="text-[10px] text-[var(--c-faint)]">{hint}</span>}
    </div>
  );
}

// ------------------------------------------------------------------- Button

export function Button({
  children,
  onClick,
  variant = "ghost",
  size = "md",
  disabled,
  title,
  className,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "outline" | "danger";
  size?: "sm" | "md";
  disabled?: boolean;
  title?: string;
  className?: string;
  type?: "button" | "submit";
}) {
  const base =
    "focus-ring inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed";
  const sizes = size === "sm" ? "px-2.5 py-1 text-[11px]" : "px-3.5 py-1.5 text-[12px]";
  const variants: Record<string, string> = {
    primary:
      "bg-[var(--c-primary)] text-[var(--c-bg)] hover:brightness-110 active:brightness-95 shadow-[0_0_20px_-8px_var(--c-primary)]",
    ghost: "text-[var(--c-muted)] hover:text-[var(--c-text)] hover:bg-[color-mix(in_oklab,var(--c-text)_9%,transparent)]",
    outline: "border border-[var(--c-line)] text-[var(--c-text)] hover:border-[var(--c-primary)] hover:text-[var(--c-primary)]",
    danger: "border border-[color-mix(in_oklab,var(--c-danger)_45%,transparent)] text-[var(--c-danger)] hover:bg-[color-mix(in_oklab,var(--c-danger)_12%,transparent)]",
  };
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick} className={`${base} ${sizes} ${variants[variant]} ${className ?? ""}`}>
      {children}
    </button>
  );
}

export function IconButton({
  label,
  onClick,
  children,
  active,
  disabled,
}: {
  label: string;
  onClick?: () => void;
  children: ReactNode;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`focus-ring grid h-7 w-7 place-items-center rounded-md border text-[var(--c-muted)] transition-colors disabled:opacity-35 ${
        active
          ? "border-[var(--c-primary)] bg-[color-mix(in_oklab,var(--c-primary)_16%,transparent)] text-[var(--c-primary)]"
          : "border-[var(--c-line)] hover:border-[var(--c-line-strong)] hover:text-[var(--c-text)]"
      }`}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ Fields

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label-xs mb-1 block">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[10px] leading-snug text-[var(--c-faint)]">{hint}</span>}
    </label>
  );
}

const inputClass =
  "focus-ring w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2.5 py-1.5 text-[12px] text-[var(--c-text)] mono-num placeholder:text-[var(--c-faint)]";

export function TextInput({
  value,
  onChange,
  placeholder,
  mono = true,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  mono?: boolean;
}) {
  return (
    <input
      className={`${inputClass} ${mono ? "" : "mono-num"}`}
      value={value}
      placeholder={placeholder}
      onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
    />
  );
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
  disabled,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <input
      type="number"
      className={inputClass}
      value={Number.isFinite(value) ? value : ""}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onChange={(event) => {
        const next = Number(event.target.value);
        onChange(Number.isFinite(next) ? next : 0);
      }}
    />
  );
}

export function Slider({
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.01,
  format,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  format?: (value: number) => string;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <input
        type="range"
        className="h-1 w-full cursor-pointer appearance-none rounded-full bg-[var(--c-line)] accent-[var(--c-primary)]"
        style={{ accentColor: "var(--c-primary)" }}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <span className="mono-num w-16 shrink-0 text-right text-[11px] text-[var(--c-text)]">
        {format ? format(value) : value.toFixed(2)}
      </span>
    </div>
  );
}

export function Select<T extends string>({
  value,
  options,
  onChange,
  disabled,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <select
      className={`${inputClass} cursor-pointer`}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as T)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value} className="bg-[var(--c-panel)] text-[var(--c-text)]">
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: Array<{ value: T; label: string; title?: string }>;
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex rounded-lg border border-[var(--c-line)] p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            title={option.title ?? option.label}
            onClick={() => onChange(option.value)}
            className={`focus-ring rounded-[6px] transition-colors ${size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-[11px]"} ${
              active
                ? "bg-[color-mix(in_oklab,var(--c-primary)_18%,transparent)] text-[var(--c-primary)]"
                : "text-[var(--c-muted)] hover:text-[var(--c-text)]"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="focus-ring flex items-center gap-2 text-[11px] text-[var(--c-muted)] hover:text-[var(--c-text)]"
    >
      <span
        className={`relative h-4 w-7 rounded-full transition-colors ${
          checked ? "bg-[var(--c-primary)]" : "bg-[var(--c-line-strong)]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-[var(--c-bg)] transition-all ${checked ? "left-3.5" : "left-0.5"}`}
        />
      </span>
      {label}
    </button>
  );
}

// ---------------------------------------------------------------- Indicators

export function Tag({ children, colour, title }: { children: ReactNode; colour?: string; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium tracking-wide"
      style={{
        borderColor: colour ? `color-mix(in oklab, ${colour} 45%, transparent)` : "var(--c-line)",
        color: colour ?? "var(--c-muted)",
        background: colour ? `color-mix(in oklab, ${colour} 10%, transparent)` : "transparent",
      }}
    >
      {children}
    </span>
  );
}

/** SIMULATED / NOISY SIMULATION / REAL HARDWARE — never blended together. */
export function ModeBadge({ mode, detail }: { mode: string; detail?: string }) {
  const colour =
    mode === "NOISY SIMULATION" ? "var(--c-warn)" : mode === "REAL HARDWARE" ? "var(--c-danger)" : "var(--c-ok)";
  return (
    <Tag colour={colour} title={detail ?? "How this result was produced"}>
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: colour }} />
      {mode}
    </Tag>
  );
}

export function StatTile({
  label,
  value,
  unit,
  hint,
  colour,
  progress,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
  colour?: string;
  progress?: number;
}) {
  return (
    <div className="panel-flat px-3 py-2.5">
      <div className="label-xs truncate">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="mono-num text-[17px] font-semibold leading-none" style={{ color: colour }}>
          {value}
        </span>
        {unit && <span className="text-[10px] text-[var(--c-faint)]">{unit}</span>}
      </div>
      {typeof progress === "number" && (
        <div className="mt-2">
          <MeterBar value={progress} colour={colour ?? "var(--c-primary)"} height={3} />
        </div>
      )}
      {hint && <div className="mt-1 truncate text-[10px] text-[var(--c-faint)]" title={hint}>{hint}</div>}
    </div>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "danger" | "ok";
  title?: string;
  children: ReactNode;
}) {
  const colours: Record<string, string> = {
    info: "var(--c-secondary)",
    warn: "var(--c-warn)",
    danger: "var(--c-danger)",
    ok: "var(--c-ok)",
  };
  return (
    <div
      className="rounded-lg border px-3 py-2 text-[11px] leading-relaxed"
      style={{
        borderColor: `color-mix(in oklab, ${colours[tone]} 35%, transparent)`,
        background: `color-mix(in oklab, ${colours[tone]} 8%, transparent)`,
      }}
    >
      {title && <div className="mb-0.5 font-semibold" style={{ color: colours[tone] }}>{title}</div>}
      <div className="text-[var(--c-muted)]">{children}</div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[11px] text-[var(--c-muted)]">
      <PulseDot />
      {label}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-lg border border-dashed border-[var(--c-line)] px-4 py-8 text-center text-[11px] text-[var(--c-faint)]">
      {children}
    </div>
  );
}

// ------------------------------------------------------------------- Tables

export function DataTable({
  columns,
  rows,
  highlight,
  onRowClick,
  selected,
}: {
  columns: Array<{ key: string; label: string; align?: "left" | "right"; width?: string; render?: (row: Record<string, unknown>) => ReactNode }>;
  rows: Array<Record<string, unknown>>;
  highlight?: (row: Record<string, unknown>) => boolean;
  onRowClick?: (row: Record<string, unknown>) => void;
  selected?: (row: Record<string, unknown>) => boolean;
}) {
  if (!rows.length) return <Empty>No rows.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-[var(--c-line)]">
            {columns.map((column) => (
              <th
                key={column.key}
                style={{ width: column.width }}
                className={`label-xs whitespace-nowrap px-2 py-1.5 ${column.align === "right" ? "text-right" : "text-left"}`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={index}
              onClick={() => onRowClick?.(row)}
              className={`border-b border-[color-mix(in_oklab,var(--c-line)_55%,transparent)] transition-colors ${
                onRowClick ? "cursor-pointer hover:bg-[color-mix(in_oklab,var(--c-text)_5%,transparent)]" : ""
              } ${selected?.(row) ? "bg-[color-mix(in_oklab,var(--c-primary)_12%,transparent)]" : ""} ${
                highlight?.(row) ? "text-[var(--c-warn)]" : ""
              }`}
            >
              {columns.map((column) => (
                <td key={column.key} className={`px-2 py-1.5 ${column.align === "right" ? "text-right mono-num" : ""}`}>
                  {column.render ? column.render(row) : String(row[column.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KeyValueList({ items, columns = 2 }: { items: Array<{ label: string; value: ReactNode }>; columns?: number }) {
  return (
    <dl className="grid gap-x-4 gap-y-1.5" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline justify-between gap-2 border-b border-[color-mix(in_oklab,var(--c-line)_45%,transparent)] pb-1">
          <dt className="text-[10px] uppercase tracking-wider text-[var(--c-faint)]">{item.label}</dt>
          <dd className="mono-num truncate text-right text-[11px] text-[var(--c-text)]" title={typeof item.value === "string" ? item.value : undefined}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function CodeBlock({ text, maxHeight = 260, caption }: { text: string; maxHeight?: number; caption?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre
        className="mono-num overflow-auto rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_78%,transparent)] p-3 text-[11px] leading-relaxed text-[var(--c-muted)]"
        style={{ maxHeight }}
      >
        {text || "—"}
      </pre>
      <div className="absolute right-2 top-2 flex items-center gap-1.5">
        {caption && <span className="text-[10px] text-[var(--c-faint)]">{caption}</span>}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            void navigator.clipboard?.writeText(text);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1400);
          }}
        >
          {copied ? "copied" : "copy"}
        </Button>
      </div>
    </div>
  );
}

// -------------------------------------------------------------- Provenance

/** Where a result came from. Shown with every number that could be mistaken for a measurement. */
export function Provenance({
  mode,
  backend,
  representation,
  exact,
  seed,
  shots,
  noise,
  seconds,
  memoryMb,
  algorithm,
  extra = [],
}: {
  mode: string;
  backend: string;
  representation?: string;
  exact?: boolean;
  seed?: number;
  shots?: number;
  noise?: string;
  seconds?: number;
  memoryMb?: number;
  algorithm?: string;
  extra?: Array<{ label: string; value: ReactNode }>;
}) {
  const items: Array<{ label: string; value: ReactNode }> = [
    { label: "engine", value: backend },
    { label: "representation", value: representation ?? "—" },
    { label: "exact", value: exact === undefined ? "—" : exact ? "yes" : "sampled / approximate" },
    { label: "seed", value: seed ?? "—" },
    { label: "shots", value: shots ?? "—" },
    { label: "error model", value: noise ?? "ideal" },
  ];
  if (algorithm) items.push({ label: "algorithm", value: algorithm });
  if (seconds !== undefined) items.push({ label: "runtime", value: `${Number(seconds).toFixed(4)} s` });
  if (memoryMb !== undefined) items.push({ label: "state memory", value: `${Number(memoryMb).toFixed(2)} MB` });
  items.push(...extra);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <ModeBadge mode={mode} />
        <span className="text-[10px] text-[var(--c-faint)]">
          provenance recorded with the result — not inferred by the interface
        </span>
      </div>
      <KeyValueList items={items} columns={3} />
    </div>
  );
}

export function WarningList({ warnings, notes }: { warnings: string[]; notes: string[] }) {

  if (!warnings.length && !notes.length) return null;
  return (
    <div className="space-y-1.5">
      {warnings.map((warning, index) => (
        <Notice key={`w-${index}`} tone="warn" title="Warning">
          {warning}
        </Notice>
      ))}
      {notes.map((note, index) => (
        <Notice key={`n-${index}`} tone="info">
          {note}
        </Notice>
      ))}
    </div>
  );
}
