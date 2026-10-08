/** Formatting helpers. Every number the interface shows goes through these. */

export function formatNumber(value: unknown, digits = 3): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return String(value);
  const magnitude = Math.abs(number);
  if (magnitude !== 0 && (magnitude < 1e-4 || magnitude >= 1e6)) return number.toExponential(2);
  if (Number.isInteger(number)) return number.toLocaleString();
  return number.toFixed(digits);
}

export function formatPercent(value: unknown, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  if (Math.abs(number) <= 1) return `${(number * 100).toFixed(digits)}%`;
  return `${number.toFixed(digits)}%`;
}

export function formatSeconds(value: unknown, digits = 3): string {
  if (value === null || value === undefined) return "—";
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "—";
  if (seconds === 0) return "0 s";
  if (seconds < 1e-3) return `${(seconds * 1e6).toFixed(0)} µs`;
  if (seconds < 1) return `${(seconds * 1e3).toFixed(digits === 3 ? 1 : digits)} ms`;
  if (seconds < 120) return `${seconds.toFixed(digits)} s`;
  return `${(seconds / 60).toFixed(1)} min`;
}

export function formatBytes(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const bytes = Number(value);
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes.toFixed(0)} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function formatMegabytes(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const mb = Number(value);
  if (!Number.isFinite(mb)) return "—";
  if (mb < 0.001) return `${(mb * 1e6).toFixed(0)} B`;
  if (mb < 1) return `${(mb * 1024).toFixed(0)} KB`;
  if (mb < 1024) return `${mb.toFixed(2)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

export function formatAngle(radians: number): string {
  const degrees = (radians * 180) / Math.PI;
  const turned = ((degrees % 360) + 360) % 360;
  return `${turned.toFixed(1)}°`;
}

/** Shared label for how many qubits a basis string implies. */
export function basisLength(counts: Record<string, number>): number {
  const first = Object.keys(counts)[0];
  return first ? first.length : 0;
}

export function sortedCounts(counts: Record<string, number>, limit = 16): Array<{ basis: string; count: number }> {
  return Object.entries(counts)
    .map(([basis, count]) => ({ basis, count }))
    .sort((a, b) => b.count - a.count || a.basis.localeCompare(b.basis))
    .slice(0, limit);
}

export function sortedProbabilities(
  probabilities: Record<string, number>,
  limit = 16,
): Array<{ basis: string; probability: number }> {
  return Object.entries(probabilities)
    .map(([basis, probability]) => ({ basis, probability }))
    .sort((a, b) => b.probability - a.probability || a.basis.localeCompare(b.basis))
    .slice(0, limit);
}

/** Human phrase for a fidelity, so a number is never mistaken for a verdict. */
export function fidelityWords(fidelity: number | null | undefined): string {
  if (fidelity === null || fidelity === undefined) return "not applicable";
  if (fidelity > 0.999) return "indistinguishable from the ideal state";
  if (fidelity > 0.99) return "very close to ideal";
  if (fidelity > 0.95) return "close to ideal";
  if (fidelity > 0.8) return "noticeably degraded";
  if (fidelity > 0.5) return "heavily degraded";
  return "dominated by error";
}

export function modeLabel(mode: string): string {
  if (mode === "SIMULATED") return "SIMULATED";
  if (mode === "NOISY SIMULATION") return "NOISY SIMULATION";
  if (mode === "REAL HARDWARE") return "REAL HARDWARE";
  return mode;
}

export function titleCase(text: string): string {
  return text.replace(/(^|[\s_-])([a-z])/g, (_, prefix: string, letter: string) => `${prefix}${letter.toUpperCase()}`).replace(/[_-]/g, " ");
}

/** A compact, stable key for React lists built from API objects. */
export function stableKey(...parts: Array<string | number>): string {
  return parts.map(String).join(":");
}
