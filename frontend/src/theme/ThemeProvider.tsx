import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  DEFAULT_THEME,
  PALETTES,
  contrastRatio,
  luminance,
  paletteVariables,
  randomPalette,
  type Palette,
  type ThemeKey,
} from "./theme";

interface ThemeState {
  colors: Record<ThemeKey, string>;
  paletteName: string;
  palette: Palette | undefined;
  mode: "dark" | "light";
  /** Contrast between text and background; the studio warns below 4.5. */
  contrast: number;
  setColor: (key: ThemeKey, value: string) => void;
  applyPalette: (palette: Palette) => void;
  randomise: () => void;
  reset: () => void;
  shareUrl: () => string;
}

const ThemeContext = createContext<ThemeState | null>(null);
const STORAGE_KEY = "qscope.theme.v1";

function readInitial(): { colors: Record<ThemeKey, string>; paletteName: string } {
  if (typeof window === "undefined") {
    return { colors: { ...DEFAULT_THEME }, paletteName: PALETTES[0].name };
  }
  // a shared URL wins over local storage, so a link reproduces someone's exact look
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const fromUrl: Partial<Record<ThemeKey, string>> = {};
  (["text", "background", "primary", "secondary", "accent"] as ThemeKey[]).forEach((key) => {
    const value = hash.get(key);
    if (value && /^[0-9a-f]{6}$/i.test(value)) fromUrl[key] = `#${value}`;
  });
  if (Object.keys(fromUrl).length === 5) {
    return { colors: { ...DEFAULT_THEME, ...fromUrl }, paletteName: "Shared link" };
  }
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as { colors?: Record<ThemeKey, string>; paletteName?: string };
      if (parsed.colors?.background && parsed.colors?.text) {
        return { colors: { ...DEFAULT_THEME, ...parsed.colors }, paletteName: parsed.paletteName ?? "Custom" };
      }
    }
  } catch {
    /* a corrupt entry is not worth failing over */
  }
  return { colors: { ...DEFAULT_THEME }, paletteName: PALETTES[0].name };
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(readInitial, []);
  const [colors, setColors] = useState<Record<ThemeKey, string>>(initial.colors);
  const [paletteName, setPaletteName] = useState(initial.paletteName);

  useEffect(() => {
    const root = document.documentElement;
    const variables = paletteVariables(colors);
    for (const [name, value] of Object.entries(variables)) {
      root.style.setProperty(name, value);
    }
    root.dataset.palette = paletteName;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ colors, paletteName }));
    } catch {
      /* private browsing: the theme simply will not persist */
    }
  }, [colors, paletteName]);

  const value = useMemo<ThemeState>(
    () => ({
      colors,
      paletteName,
      palette: PALETTES.find((entry) => entry.name === paletteName),
      mode: luminance(colors.background) > 0.5 ? "light" : "dark",
      contrast: contrastRatio(colors.text, colors.background),
      setColor: (key, colour) => {
        setColors((previous) => ({ ...previous, [key]: colour }));
        setPaletteName("Custom");
      },
      applyPalette: (palette) => {
        setColors({ ...palette.colors });
        setPaletteName(palette.name);
      },
      randomise: () => {
        setColors(randomPalette());
        setPaletteName("Surprise");
      },
      reset: () => {
        setColors({ ...DEFAULT_THEME });
        setPaletteName(PALETTES[0].name);
      },
      shareUrl: () => {
        const hash = new URLSearchParams(
          Object.entries(colors).map(([key, colour]) => [key, colour.replace("#", "")]),
        ).toString();
        return `${window.location.origin}${window.location.pathname}#${hash}`;
      },
    }),
    [colors, paletteName],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside <ThemeProvider>");
  return context;
}
