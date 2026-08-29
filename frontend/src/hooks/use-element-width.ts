"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The rendered pixel width of an element, kept current as it changes.
 *
 * A chart drawn into a fixed `viewBox` and stretched to fit its card is drawn at whatever scale the
 * browser picks: its labels shrink in a narrow column and balloon in a wide one, and where the
 * card's aspect ratio does not match the box, the plot is letterboxed inside its own frame with
 * empty margins either side. Measuring the container and drawing at that width in real pixels
 * avoids all of it - a 9px label is 9px on every screen, and the plot fills the space it is given.
 *
 * `fallback` is what a server render, and any environment without a ResizeObserver, draws at - so
 * the chart is a complete, correct picture before the first measurement arrives rather than a
 * flash of nothing.
 */
export function useElementWidth<T extends HTMLElement>(
  fallback: number,
): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;

    const measure = () => setWidth(Math.max(240, Math.round(element.clientWidth)));
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, width];
}
