/**
 * Motion primitives.
 *
 * The same idea as the Motion Primitives collection: small, copy-in components
 * built on `motion` that carry the interface's movement.  They are deliberately
 * small and composable — a research instrument should animate to show *change*,
 * not to decorate — so every one of them is used to reveal information (a value
 * counting up, a panel swapping, a state difference appearing).
 */

import {
  AnimatePresence,
  motion,
  useInView,
  useMotionTemplate,
  useMotionValue,
  useScroll,
  useSpring,
  useTransform,
  type Variants,
} from "motion/react";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

// ------------------------------------------------------------------ InView

export interface InViewProps {
  children: ReactNode;
  variants?: Variants;
  className?: string;
  delay?: number;
  once?: boolean;
}

const riseVariants: Variants = {
  hidden: { opacity: 0, y: 14, filter: "blur(6px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)" },
};

/** Reveals its children once they scroll into view. */
export function InView({ children, variants = riseVariants, className, delay = 0, once = true }: InViewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once, margin: "-60px 0px -40px 0px" });
  return (
    <motion.div
      ref={ref}
      className={className}
      initial="hidden"
      animate={inView ? "visible" : "hidden"}
      variants={variants}
      transition={{ duration: 0.5, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}

/** A staggered container: children animate in sequence. */
export function AnimatedGroup({
  children,
  className,
  stagger = 0.05,
  once = true,
}: {
  children: ReactNode;
  className?: string;
  stagger?: number;
  once?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once, margin: "-40px" });
  return (
    <motion.div
      ref={ref}
      className={className}
      initial="hidden"
      animate={inView ? "visible" : "hidden"}
      variants={{ hidden: {}, visible: { transition: { staggerChildren: stagger } } }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={riseVariants} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
      {children}
    </motion.div>
  );
}

// ---------------------------------------------------------- AnimatedNumber

/** Counts to a value with a spring, so a changing measurement reads as movement. */
export function AnimatedNumber({
  value,
  digits = 3,
  className,
  suffix = "",
  prefix = "",
}: {
  value: number | null | undefined;
  digits?: number;
  className?: string;
  suffix?: string;
  prefix?: string;
}) {
  const safe = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const spring = useSpring(safe, { stiffness: 90, damping: 20, mass: 0.6 });
  const [display, setDisplay] = useState(safe);

  useEffect(() => {
    spring.set(safe);
  }, [safe, spring]);

  useEffect(() => {
    const unsubscribe = spring.on("change", (latest) => setDisplay(latest));
    return () => unsubscribe();
  }, [spring]);

  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return <span className={className}>—</span>;
  }
  const magnitude = Math.abs(safe);
  const text = magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e5) ? safe.toExponential(2) : display.toFixed(digits);
  return (
    <span className={className}>
      {prefix}
      {text}
      {suffix}
    </span>
  );
}

// ------------------------------------------------------------- TextShimmer

/** A moving sheen across text — used for in-progress labels, never for results. */
export function TextShimmer({ children, className }: { children: string; className?: string }) {
  return (
    <span
      className={className}
      style={{
        backgroundImage:
          "linear-gradient(100deg, color-mix(in oklab, var(--c-muted) 80%, transparent) 20%, var(--c-text) 42%, var(--c-primary) 50%, var(--c-text) 58%, color-mix(in oklab, var(--c-muted) 80%, transparent) 80%)",
        backgroundSize: "200% 100%",
        WebkitBackgroundClip: "text",
        backgroundClip: "text",
        color: "transparent",
        animation: "var(--animate-shimmer)",
      }}
    >
      {children}
    </span>
  );
}

// ------------------------------------------------------------- TextEffect

/** Reveals a heading word by word. */
export function TextEffect({
  text,
  className,
  per = "word",
  delay = 0,
}: {
  text: string;
  className?: string;
  per?: "word" | "char";
  delay?: number;
}) {
  const pieces = per === "word" ? text.split(" ") : text.split("");
  return (
    <motion.span
      className={className}
      initial="hidden"
      animate="visible"
      variants={{ hidden: {}, visible: { transition: { staggerChildren: per === "word" ? 0.055 : 0.017, delayChildren: delay } } }}
    >
      {pieces.map((piece, index) => (
        <motion.span
          key={`${piece}-${index}`}
          className="inline-block"
          variants={{ hidden: { opacity: 0, y: 12, filter: "blur(5px)" }, visible: { opacity: 1, y: 0, filter: "blur(0px)" } }}
          transition={{ duration: 0.42, ease: [0.16, 1, 0.3, 1] }}
        >
          {piece}
          {per === "word" && index < pieces.length - 1 ? "\u00A0" : ""}
        </motion.span>
      ))}
    </motion.span>
  );
}

// ------------------------------------------------------ TransitionPanel

/** Cross-fades between panels of different heights (the mode switcher). */
export function TransitionPanel({ activeKey, children }: { activeKey: string; children: ReactNode }) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={activeKey}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// --------------------------------------------------------------- Spotlight

/** A pointer-following highlight. Used on the mission-control tiles. */
export function Spotlight({ children, className, colour = "var(--c-primary)" }: { children: ReactNode; className?: string; colour?: string }) {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);
  const opacity = useMotionValue(0);
  const background = useMotionTemplate`radial-gradient(360px circle at ${mouseX}px ${mouseY}px, color-mix(in oklab, ${colour} 22%, transparent), transparent 72%)`;

  return (
    <div
      className={className}
      style={{ position: "relative" }}
      onPointerMove={(event) => {
        const bounds = event.currentTarget.getBoundingClientRect();
        mouseX.set(event.clientX - bounds.left);
        mouseY.set(event.clientY - bounds.top);
        opacity.set(1);
      }}
      onPointerLeave={() => opacity.set(0)}
    >
      <motion.div style={{ background, opacity }} className="pointer-events-none absolute inset-0 rounded-[inherit]" />
      <div style={{ position: "relative" }}>{children}</div>
    </div>
  );
}

// ------------------------------------------------------------- GlowEffect

/** A slowly rotating glow border for the active instrument panel. */
export function GlowEffect({ children, className, active = true }: { children: ReactNode; className?: string; active?: boolean }) {
  return (
    <div className={`relative ${className ?? ""}`}>
      {active && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute -inset-px rounded-[inherit] opacity-60"
          style={{
            background:
              "conic-gradient(from 0deg, transparent 0deg, color-mix(in oklab, var(--c-primary) 55%, transparent) 90deg, transparent 200deg, color-mix(in oklab, var(--c-secondary) 45%, transparent) 300deg, transparent 360deg)",
            filter: "blur(9px)",
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: 18, repeat: Infinity, ease: "linear" }}
        />
      )}
      <div className="relative">{children}</div>
    </div>
  );
}

// ------------------------------------------------------------ ScrollProgress

export function ScrollProgress({ target }: { target?: React.RefObject<HTMLElement | null> }) {
  const { scrollYProgress } = useScroll(target ? { container: target } : undefined);
  const width = useTransform(scrollYProgress, [0, 1], ["0%", "100%"]);
  return (
    <motion.div
      aria-hidden
      className="sticky top-0 z-20 h-[2px] origin-left"
      style={{ width, background: "linear-gradient(90deg, var(--c-primary), var(--c-secondary), var(--c-accent))" }}
    />
  );
}

// -------------------------------------------------------------------- Tilt

/** Subtle pointer tilt for cards; disabled for reduced-motion users by CSS. */
export function Tilt({ children, className, strength = 6 }: { children: ReactNode; className?: string; strength?: number }) {
  const rotateX = useSpring(0, { stiffness: 140, damping: 18 });
  const rotateY = useSpring(0, { stiffness: 140, damping: 18 });
  return (
    <motion.div
      className={className}
      style={{ rotateX, rotateY, transformPerspective: 900 }}
      onPointerMove={(event) => {
        const bounds = event.currentTarget.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width - 0.5;
        const y = (event.clientY - bounds.top) / bounds.height - 0.5;
        rotateY.set(x * strength * 2);
        rotateX.set(-y * strength * 2);
      }}
      onPointerLeave={() => {
        rotateY.set(0);
        rotateX.set(0);
      }}
    >
      {children}
    </motion.div>
  );
}

// ------------------------------------------------------------------ Reveal

/** A width-animated bar, used for every measured quantity in the interface. */
export function MeterBar({
  value,
  colour = "var(--c-primary)",
  height = 6,
  className,
  delay = 0,
}: {
  value: number;
  colour?: string;
  height?: number;
  className?: string;
  delay?: number;
}) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const style: CSSProperties = { height, background: colour };
  return (
    <div className={`w-full overflow-hidden rounded-full bg-[var(--c-line)]/60 ${className ?? ""}`} style={{ height }}>
      <motion.div
        className="h-full rounded-full"
        style={style}
        initial={{ width: 0 }}
        animate={{ width: `${clamped * 100}%` }}
        transition={{ duration: 0.7, delay, ease: [0.16, 1, 0.3, 1] }}
      />
    </div>
  );
}

/** A pulsing status dot; the only looping animation in the interface. */
export function PulseDot({ colour = "var(--c-primary)", size = 7 }: { colour?: string; size?: number }) {
  return (
    <span className="relative inline-flex" style={{ width: size, height: size }}>
      <motion.span
        className="absolute inset-0 rounded-full"
        style={{ background: colour }}
        animate={{ opacity: [0.85, 0.25, 0.85], scale: [1, 1.35, 1] }}
        transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
      />
      <span className="absolute inset-0 rounded-full" style={{ background: colour }} />
    </span>
  );
}
