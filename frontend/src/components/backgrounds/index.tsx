/**
 * Haikei-style backdrops, as components.
 *
 * Haikei's generators (layered waves, stacked waves, blobs, poly grids) produce
 * SVG assets; these are the same shapes drawn live from the palette, so a
 * backdrop follows the Realtime Colors theme instead of being baked to one
 * palette.  The static, generated SVG files in `public/backdrops/` come from
 * `tools/make_backdrops.py` and are used where a file is wanted instead.
 */

interface BackdropProps {
  className?: string;
  opacity?: number;
  palette?: { primary: string; secondary: string; accent: string; background: string };
}

const FALLBACK = {
  primary: "var(--c-primary)",
  secondary: "var(--c-secondary)",
  accent: "var(--c-accent)",
  background: "var(--c-bg)",
};

/** Haikei "Layered Waves": stacked smooth wave bands. */
export function LayeredWaves({ className, opacity = 0.5, palette = FALLBACK }: BackdropProps) {
  return (
    <svg
      aria-hidden
      className={className}
      viewBox="0 0 1440 720"
      preserveAspectRatio="none"
      style={{ opacity, color: palette.primary }}
    >
      <defs>
        <linearGradient id="lw-a" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={palette.primary} stopOpacity="0.42" />
          <stop offset="100%" stopColor={palette.secondary} stopOpacity="0.08" />
        </linearGradient>
        <linearGradient id="lw-b" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor={palette.secondary} stopOpacity="0.34" />
          <stop offset="100%" stopColor={palette.accent} stopOpacity="0.06" />
        </linearGradient>
      </defs>
      <path
        fill="url(#lw-a)"
        d="M0 430 C 180 350 320 470 520 420 C 720 370 820 250 1010 300 C 1180 345 1300 300 1440 350 L1440 720 L0 720 Z"
      />
      <path
        fill="url(#lw-b)"
        d="M0 520 C 200 470 340 560 540 520 C 760 476 880 380 1080 420 C 1240 452 1340 430 1440 460 L1440 720 L0 720 Z"
      />
      <path
        fill={palette.background}
        fillOpacity="0.35"
        d="M0 610 C 220 570 360 640 560 610 C 780 576 900 500 1100 540 C 1260 572 1350 560 1440 585 L1440 720 L0 720 Z"
      />
    </svg>
  );
}

/** Haikei "Stacked Waves": nested wave lines, read as a spectrogram. */
export function StackedWaves({ className, opacity = 0.6, palette = FALLBACK }: BackdropProps) {
  const rows = Array.from({ length: 9 }, (_, index) => index);
  return (
    <svg aria-hidden className={className} viewBox="0 0 1440 480" preserveAspectRatio="none" style={{ opacity }}>
      {rows.map((row) => {
        const baseline = 60 + row * 44;
        const amplitude = 12 + row * 2.6;
        const shift = row * 37;
        const colour = row % 3 === 0 ? palette.primary : row % 3 === 1 ? palette.secondary : palette.accent;
        return (
          <path
            key={row}
            fill="none"
            stroke={colour}
            strokeOpacity={0.5 - row * 0.035}
            strokeWidth={1.4}
            d={`M -40 ${baseline} C 220 ${baseline - amplitude} 420 ${baseline + amplitude} 720 ${baseline - amplitude * 0.5} C 980 ${baseline - amplitude * 1.3} 1180 ${baseline + amplitude * 0.7} 1480 ${baseline + shift * 0.02}`}
          />
        );
      })}
    </svg>
  );
}

/** Haikei "Blob Scene": soft organic blobs behind the hero. */
export function BlobScene({ className, opacity = 0.55, palette = FALLBACK }: BackdropProps) {
  return (
    <svg aria-hidden className={className} viewBox="0 0 900 600" style={{ opacity }}>
      <defs>
        <radialGradient id="blob-a" cx="35%" cy="35%" r="70%">
          <stop offset="0%" stopColor={palette.primary} stopOpacity="0.5" />
          <stop offset="100%" stopColor={palette.primary} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="blob-b" cx="60%" cy="45%" r="70%">
          <stop offset="0%" stopColor={palette.secondary} stopOpacity="0.45" />
          <stop offset="100%" stopColor={palette.secondary} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="blob-c" cx="50%" cy="65%" r="70%">
          <stop offset="0%" stopColor={palette.accent} stopOpacity="0.32" />
          <stop offset="100%" stopColor={palette.accent} stopOpacity="0" />
        </radialGradient>
      </defs>
      <path
        fill="url(#blob-a)"
        d="M420 40 C 560 30 690 120 700 250 C 710 390 600 500 450 505 C 300 510 170 420 160 285 C 150 150 280 50 420 40 Z"
      />
      <path
        fill="url(#blob-b)"
        d="M300 210 C 400 190 520 250 530 350 C 540 450 450 540 340 535 C 220 530 140 450 150 350 C 160 260 200 230 300 210 Z"
      />
      <path
        fill="url(#blob-c)"
        d="M600 300 C 690 290 770 340 775 415 C 780 495 700 545 620 540 C 535 535 480 480 490 410 C 500 340 520 308 600 300 Z"
      />
    </svg>
  );
}

/** Haikei "Poly Grid": a warped lattice, useful behind data views. */
export function PolyGrid({ className, opacity = 0.28, palette = FALLBACK }: BackdropProps) {
  const size = 18;
  const spacing = 72;
  const lines: string[] = [];
  for (let index = -1; index <= size; index += 1) {
    const offset = index * spacing;
    lines.push(`M ${offset} 0 L ${offset + size * 22} ${size * spacing}`);
    lines.push(`M ${offset} 0 L ${offset - size * 22} ${size * spacing}`);
  }
  return (
    <svg aria-hidden className={className} viewBox={`0 0 ${size * spacing} ${size * spacing}`} preserveAspectRatio="xMidYMid slice" style={{ opacity }}>
      <g stroke={palette.primary} strokeWidth="0.6" fill="none">
        {lines.map((d, index) => (
          <path key={index} d={d} strokeOpacity={0.15 + (index % 7) * 0.02} />
        ))}
      </g>
      <rect width="100%" height="100%" fill="none" />
      <g stroke={palette.secondary} strokeWidth="0.4" strokeOpacity="0.2">
        {Array.from({ length: size }, (_, row) => (
          <path key={row} d={`M 0 ${row * spacing} L ${size * spacing} ${row * spacing + (row % 3) * 9}`} fill="none" />
        ))}
      </g>
    </svg>
  );
}

/** Haikei "Circle Scatter": a constellation of orbit rings. */
export function CircleScatter({ className, opacity = 0.4, palette = FALLBACK }: BackdropProps) {
  const rings = [
    { cx: 180, cy: 150, r: 60 },
    { cx: 640, cy: 90, r: 34 },
    { cx: 420, cy: 320, r: 88 },
    { cx: 880, cy: 260, r: 46 },
    { cx: 260, cy: 470, r: 28 },
    { cx: 760, cy: 500, r: 66 },
  ];
  return (
    <svg aria-hidden className={className} viewBox="0 0 1000 620" style={{ opacity }}>
      {rings.map((ring, index) => (
        <g key={index} stroke={index % 2 ? palette.secondary : palette.primary} fill="none" strokeWidth="1">
          <circle cx={ring.cx} cy={ring.cy} r={ring.r} strokeOpacity="0.45" />
          <circle cx={ring.cx} cy={ring.cy} r={ring.r * 0.62} strokeOpacity="0.28" strokeDasharray="3 7" />
          <circle cx={ring.cx + ring.r} cy={ring.cy} r="2.4" fill={palette.accent} stroke="none" />
        </g>
      ))}
    </svg>
  );
}

/** The composed hero backdrop: blobs, waves and a faint lattice. */
export function HeroBackdrop({ className }: { className?: string }) {
  return (
    <div className={className} aria-hidden style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: "-10%", animation: "var(--animate-drift)" }}>
        <BlobScene className="absolute inset-0 h-full w-full" opacity={0.5} />
      </div>
      <LayeredWaves className="absolute bottom-0 left-0 h-[62%] w-full" opacity={0.42} />
      <PolyGrid className="absolute inset-0 h-full w-full" opacity={0.16} />
      <div
        className="hairline-grid"
        style={{ position: "absolute", inset: 0, opacity: 0.25, maskImage: "radial-gradient(60% 60% at 50% 40%, black, transparent)" }}
      />
    </div>
  );
}
