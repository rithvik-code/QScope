/**
 * The palette model, in the spirit of Realtime Colors.
 *
 * A theme is five decisions — text, background, primary, secondary, accent — and
 * everything else is derived: four neutral ramps built by mixing background and
 * text, a tint ramp built from the primary, and semantic surface tokens.  The
 * values are written as CSS variables so a change repaints the whole instrument
 * without a re-render of every component.
 */

export type ThemeKey = "text" | "background" | "primary" | "secondary" | "accent";

export interface Palette {
  name: string;
  note: string;
  mode: "dark" | "light";
  colors: Record<ThemeKey, string>;
}

export const PALETTES: Palette[] = [
  {
    name: "Scientific",
    note: "The default instrument palette: cold neutrals, a cyan signal colour.",
    mode: "dark",
    colors: { text: "#e9edf5", background: "#080a10", primary: "#6ee7c8", secondary: "#7aa2ff", accent: "#ff8ad4" },
  },
  {
    name: "Deep Field",
    note: "Violet primary, cyan secondary — good for long observing sessions.",
    mode: "dark",
    colors: { text: "#dfe7ff", background: "#05070f", primary: "#8b7cff", secondary: "#35d0ff", accent: "#ff9d5c" },
  },
  {
    name: "Graphite",
    note: "Neutral and quiet; the numbers carry the colour.",
    mode: "dark",
    colors: { text: "#e6e8ea", background: "#0d0f11", primary: "#9ad5ff", secondary: "#b9a5ff", accent: "#8be28b" },
  },
  {
    name: "Amber CRT",
    note: "A warm scope face, for reading phase plots at a glance.",
    mode: "dark",
    colors: { text: "#f3e7d3", background: "#0c0a08", primary: "#ffb347", secondary: "#ff7a59", accent: "#7dd3fc" },
  },
  {
    name: "Blueprint",
    note: "Engineering white-on-blue, closest to a printed schematic.",
    mode: "dark",
    colors: { text: "#d8eefb", background: "#061620", primary: "#38bdf8", secondary: "#a7f3d0", accent: "#fda4af" },
  },
  {
    name: "Laboratory",
    note: "A light palette for projectors and printed screenshots.",
    mode: "light",
    colors: { text: "#14161c", background: "#f5f6fa", primary: "#0f766e", secondary: "#2456d6", accent: "#b4326f" },
  },
];

export const DEFAULT_THEME: Record<ThemeKey, string> = { ...PALETTES[0].colors };

// ---------------------------------------------------------------------- colour maths

interface RGB {
  r: number;
  g: number;
  b: number;
}

export function hexToRgb(hex: string): RGB {
  const clean = hex.replace("#", "").trim();
  const full = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean.padEnd(6, "0");
  return {
    r: parseInt(full.slice(0, 2), 16) || 0,
    g: parseInt(full.slice(2, 4), 16) || 0,
    b: parseInt(full.slice(4, 6), 16) || 0,
  };
}

export function rgbToHex({ r, g, b }: RGB): string {
  const clamp = (value: number) => Math.max(0, Math.min(255, Math.round(value)));
  return `#${[r, g, b].map((value) => clamp(value).toString(16).padStart(2, "0")).join("")}`;
}

/** Linear interpolation between two hex colours, `t` from 0 to 1. */
export function mix(a: string, b: string, t: number): string {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  return rgbToHex({ r: x.r + (y.r - x.r) * t, g: x.g + (y.g - x.g) * t, b: x.b + (y.b - x.b) * t });
}

export function luminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const channel = (value: number) => {
    const v = value / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio, used to warn when a palette choice is unreadable. */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** A 10-step ramp from `dark` to `light` through `colour`, in the Realtime Colors spirit. */
function ramp(colour: string, dark: string, light: string): Record<string, string> {
  const steps: Record<string, string> = {};
  const names = ["100", "200", "300", "400", "500", "600", "700", "800", "900"];
  names.forEach((name, index) => {
    const t = index / (names.length - 1);
    // blend towards the extremes more aggressively at the ends so the ramp keeps hue
    const eased = t < 0.5 ? 0.5 * (t * 2) ** 1.15 : 1 - 0.5 * ((1 - t) * 2) ** 1.15;
    steps[name] = mix(dark, light, eased);
  });
  steps["50"] = mix(light, "#ffffff", 0.6);
  steps["950"] = mix(dark, "#000000", 0.35);
  // the 500 slot is the source colour itself, so the ramp always contains the choice
  steps["500"] = colour;
  return steps;
}

/** Every CSS variable a palette implies. */
export function paletteVariables(colors: Record<ThemeKey, string>): Record<string, string> {
  const background = colors.background;
  const text = colors.text;
  const light = luminance(background) > 0.5;
  const dark = light ? "#0b0d12" : "#05060a";
  const pale = light ? "#ffffff" : "#f7faff";

  const variables: Record<string, string> = {
    "--rtc-text": text,
    "--rtc-background": background,
    "--rtc-primary": colors.primary,
    "--rtc-secondary": colors.secondary,
    "--rtc-accent": colors.accent,
  };

  for (const [name, value] of Object.entries(ramp(text, background, pale))) {
    variables[`--rtc-grey-${name}`] = value;
  }
  for (const [name, value] of Object.entries(ramp(colors.primary, dark, "#ffffff"))) {
    variables[`--rtc-tint-${name}`] = value;
  }
  // semantic surfaces, derived from the two neutral extremes
  variables["--c-bg"] = background;
  variables["--c-text"] = text;
  variables["--c-primary"] = colors.primary;
  variables["--c-secondary"] = colors.secondary;
  variables["--c-accent"] = colors.accent;
  return variables;
}

/** A pseudo-random palette, for the "surprise me" control in the palette studio. */
export function randomPalette(): Record<ThemeKey, string> {
  const hue = Math.random() * 360;
  const hsl = (h: number, s: number, l: number) => {
    const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
    const f = (n: number) => {
      const k = (n + h / 30) % 12;
      const value = l / 100 - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
      return Math.round(255 * value)
        .toString(16)
        .padStart(2, "0");
    };
    return `#${f(0)}${f(8)}${f(4)}`;
  };
  const dark = Math.random() > 0.25;
  return {
    background: hsl(hue, dark ? 26 : 22, dark ? 5 : 96),
    text: hsl(hue, dark ? 18 : 30, dark ? 94 : 9),
    primary: hsl((hue + 150) % 360, 68, dark ? 62 : 34),
    secondary: hsl((hue + 45) % 360, 72, dark ? 66 : 40),
    accent: hsl((hue + 300) % 360, 74, dark ? 68 : 44),
  };
}
