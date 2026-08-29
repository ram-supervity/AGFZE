"use client";

import { useCallback, useRef, type KeyboardEvent } from "react";

/**
 * Keyboard navigation for a horizontal tablist, per the WAI-ARIA Tabs authoring pattern.
 *
 * Two things make a set of buttons a tablist rather than a row of buttons, and only one of them is
 * markup. The ARIA roles say what it is; this says how it behaves. Without it a tab strip puts
 * every tab in the page's tab order, so somebody reaching the exception queue by keyboard has to
 * step through ten tabs to get past them, and the arrow keys - which is what a screen-reader user
 * expects to work here - do nothing at all.
 *
 * Roving tabindex: exactly one tab is focusable at a time, so Tab enters and leaves the strip in
 * one press and the arrows move within it. Selection follows focus, which is the right choice for
 * this platform's tabs because each one is a cheap filtered read rather than an expensive panel.
 *
 * Horizontal only, deliberately. Left/Right is correct for a `flex` strip and Up/Down would be
 * correct for a stacked one; a hook that guessed would get it wrong for one of them. If a vertical
 * tablist ever appears, give this an orientation argument rather than assuming.
 */
export function useRovingTabs(count: number, onSelect: (index: number) => void) {
  const refs = useRef<(HTMLElement | null)[]>([]);

  const register = useCallback(
    (index: number) => (node: HTMLElement | null) => {
      refs.current[index] = node;
    },
    [],
  );

  const focusTab = useCallback(
    (index: number) => {
      const node = refs.current[index];
      if (node) node.focus();
      onSelect(index);
    },
    [onSelect],
  );

  const onKeyDown = useCallback(
    (index: number) => (event: KeyboardEvent<HTMLElement>) => {
      // A strip with one tab has nowhere to move to. Wrapping to itself would still fire a
      // selection, so it is a genuine no-op rather than a cheap one.
      if (count < 2) return;

      let next: number | null = null;
      if (event.key === "ArrowRight") next = (index + 1) % count;
      else if (event.key === "ArrowLeft") next = (index - 1 + count) % count;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = count - 1;

      if (next === null) return;
      // Only once a key is genuinely handled. Swallowing Home and End unconditionally would stop
      // them scrolling the page from a tab strip that had nothing to do with them.
      event.preventDefault();
      focusTab(next);
    },
    [count, focusTab],
  );

  /** What a tab at this index needs: its place in the tab order, and its key handler. */
  const tabProps = useCallback(
    (index: number, selected: boolean) => ({
      ref: register(index),
      tabIndex: selected ? 0 : -1,
      onKeyDown: onKeyDown(index),
    }),
    [register, onKeyDown],
  );

  return { tabProps };
}
