/** Field guide — the "what is everything here and how do I use it?" layer.
 *
 * One composable, reused on every mode. Each guide is a short, real-English
 * walkthrough of the controls on that page, in the order a newcomer would
 * use them, with plain-language explanations of what each control actually
 * does. It is not a wall of text: a few steps, each with a heading, a
 * paragraph, and an optional pointer to where the relevant control lives.
 *
 * Dismissing it remembers the choice per mode, so the guide stays out of the
 * way once a page is understood — and can be brought back by clearing storage.
 */

import { useState } from "react";
import { AnimatedNumber } from "./motion";
import { Button } from "./ui";
import { StackedWaves } from "./backgrounds";

export interface GuideStep {
  /** Short heading, as it would appear in a manual table of contents. */
  title: string;
  /** One or two sentences in plain English. Please avoid the word "respectively". */
  body: string;
  /** Where to look on the page. Optional. */
  pointer?: string;
  /** A number shown with an animated counter when the step renders. */
  highlight?: number;
  /** Optional caption shown next to the highlight. */
  tip?: string;
}

export interface GuideSlide {
  heading: string;
  steps: GuideStep[];
}

interface FieldGuideProps {
  /** One slide per mode page, in the order the user should read them. */
  slides: GuideSlide[];
  /** The mode name, used in the header and as the dismissal key. */
  modeName: string;
  /** Called after the guide hides itself, so the page can react if it wants to. */
  onDismiss?: () => void;
}

const STORAGE_KEY = "qscope.guide.dismissed.v1";

function dismissedModes(): Set<string> {
  try {
    const raw = typeof localStorage !== "undefined" ? (localStorage.getItem(STORAGE_KEY) ?? "") : "";
    return new Set(raw.split(",").filter(Boolean));
  } catch {
    return new Set();
  }
}

function rememberDismissed(next: Set<string>) {
  try {
    localStorage.setItem(STORAGE_KEY, Array.from(next).join(","));
  } catch {
    /* storage is best-effort: the guide simply reappears next session */
  }
}

export function FieldGuide({ slides, modeName, onDismiss }: FieldGuideProps) {
  const [slide, setSlide] = useState(0);
  // bumping this re-reads localStorage, which is what hides the panel
  const [, setDismissedTick] = useState(0);

  if (slides.length === 0 || dismissedModes().has(modeName)) {
    return null;
  }

  const current = slides[slide];
  const progress = slides.length > 1 ? (slide + 1) / slides.length : 1;
  const isLast = slide >= slides.length - 1;

  const dismiss = () => {
    const next = dismissedModes();
    next.add(modeName);
    rememberDismissed(next);
    onDismiss?.();
    setDismissedTick((value) => value + 1);
  };

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-[var(--c-line-strong)] bg-[color-mix(in_oklab,var(--c-panel)_82%,transparent)] p-4 shadow-[0_10px_40px_-18px_var(--c-line)]"
      style={{ maxWidth: 560 }}
    >
      {/* background */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <StackedWaves className="h-full w-full" opacity={0.28} />
      </div>

      {/* header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="label-xs uppercase tracking-wider text-[var(--c-faint)]">Field guide</div>
          <div className="mt-0.5 font-semibold text-[var(--c-text)]">{modeName}</div>
          <p className="mt-0.5 text-[11px] leading-snug text-[var(--c-muted)]">{current.heading}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="mono-num text-[11px] text-[var(--c-muted)]">
            {slide + 1} / {slides.length}
          </div>
          {slides.length > 1 && (
            <div className="mt-1 h-1 w-12 rounded-full bg-[var(--c-line)]">
              <div
                className="h-1 rounded-full bg-[var(--c-primary)] transition-all duration-300"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
          )}
        </div>
      </div>

      {/* body */}
      <div className="mt-4 space-y-3 text-[12px] leading-relaxed text-[var(--c-text)]">
        {current.steps.map((step) => (
          <div
            key={step.title}
            className="rounded-lg border border-[color-mix(in_oklab,var(--c-line)_55%,transparent)] bg-[color-mix(in_oklab,var(--c-bg)_55%,transparent)] p-3"
          >
            <div className="font-medium text-[var(--c-primary)]">{step.title}</div>
            <p className="mt-1 leading-relaxed text-[var(--c-muted)]">{step.body}</p>
            {step.highlight !== undefined && (
              <div className="mt-1.5 flex items-baseline gap-1.5 text-[var(--c-accent)]">
                <AnimatedNumber value={step.highlight} digits={0} />
                {step.tip && <span className="text-[10px] text-[var(--c-faint)]">{step.tip}</span>}
              </div>
            )}
            {step.pointer && <p className="mt-1 text-[10px] text-[var(--c-faint)]">{step.pointer}</p>}
          </div>
        ))}
      </div>

      {/* navigation */}
      <div className="mt-4 flex items-center justify-between gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={slide === 0}
          onClick={() => setSlide((value) => Math.max(0, value - 1))}
        >
          ← back
        </Button>
        <div className="flex gap-1.5">
          <Button variant="ghost" size="sm" onClick={dismiss}>
            skip this guide
          </Button>
          {isLast ? (
            <Button size="sm" onClick={dismiss}>
              got it
            </Button>
          ) : (
            <Button size="sm" onClick={() => setSlide((value) => Math.min(slides.length - 1, value + 1))}>
              next →
            </Button>
          )}
        </div>
      </div>

      {/* one-line orientation under the buttons */}
      <p className="mt-3 border-t border-[var(--c-line)] pt-2 text-[10px] leading-relaxed text-[var(--c-faint)]">
        QScope is honest about what it simulates and what it measures. If a panel says "simulated", it means the
        engine computed the answer on your machine — not read from a real quantum computer.
      </p>
    </div>
  );
}
