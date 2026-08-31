"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { completeOnboarding } from "@/lib/api-client";
import { hasAnyRole, type PlatformRole } from "@/lib/roles";

interface Step {
  title: string;
  body: string;
  /** Which screen this step is about. Only shown to somebody who can actually reach it. */
  roles?: readonly PlatformRole[];
}

const APPROVAL_ROLES: readonly PlatformRole[] = ["approver_hod", "admin"];

const STEPS: Step[] = [
  {
    title: "Everything arrives here",
    body: "Trade email and its attachments land in the Inbox, are classified and read automatically, and wait for you there. Nothing is filed anywhere until a person has looked at it.",
  },
  {
    title: "The workspace is where a deal is checked",
    body: "Extracted figures, what they were matched against, and every business rule that has been run - with the machine's own confidence shown beside each value. You can correct anything, and a correction always asks why.",
  },
  {
    title: "Nothing is committed without a decision",
    body: "A transaction that passes its checks goes to an approver, and only a recorded approval lets it post downstream. You will not be asked to approve your own work.",
    roles: APPROVAL_ROLES,
  },
];

// Unhurried on purpose. This platform's job is to be trusted with a deal's figures, and a tooltip
// that springs at somebody works against that - so a slow fade and a small rise, no bounce, no
// overshoot. 240ms is long enough to read as deliberate and short enough not to be in the way.
const EASE = [0.22, 0.61, 0.36, 1] as const;
const DURATION = 0.24;

export interface OnboardingWalkthroughProps {
  roles: PlatformRole[];
  /** False for a first-time account. The server owns this; nothing here guesses from storage. */
  completed: boolean;
}

/**
 * The first-login walkthrough: three dismissible callouts, shown once ever.
 *
 * "Once ever" is a server fact rather than a browser one. A flag in localStorage would show the
 * tour again on a second device and lose it when somebody cleared their site data, which is the
 * sort of small dishonesty that makes a platform feel unreliable.
 *
 * The approval step is filtered out for accounts without approval rights rather than shown and
 * then explained away - a walkthrough that describes a screen the reader cannot open teaches them
 * that this platform's guidance is approximate.
 */
export function OnboardingWalkthrough({ roles, completed }: OnboardingWalkthroughProps) {
  const steps = STEPS.filter((step) => !step.roles || hasAnyRole(roles, step.roles));
  const [index, setIndex] = useState(0);
  const [open, setOpen] = useState(!completed && steps.length > 0);

  const { data: session } = useSession();
  const token = session?.accessToken;

  const finish = useCallback(() => {
    setOpen(false);
    // Best effort, and deliberately not awaited or surfaced. If the write fails the worst outcome
    // is that the tour appears once more; blocking the person behind a spinner, or showing them an
    // error about a tooltip, would both be worse than that.
    if (token) void completeOnboarding(token).catch(() => undefined);
  }, [token]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") finish();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, finish]);

  if (!open) return null;
  const step = steps[index];
  const last = index === steps.length - 1;

  return (
    <AnimatePresence>
      <motion.div
        key="onboarding"
        role="dialog"
        aria-modal="false"
        aria-labelledby="onboarding-title"
        aria-describedby="onboarding-body"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 8 }}
        transition={{ duration: DURATION, ease: EASE }}
        className="fixed bottom-space-200 right-space-200 z-popover w-[min(24rem,calc(100vw-2rem))] rounded-medium border-thin border-border bg-elevation-overlay p-space-200 shadow-raised"
      >
        <p className="text-xs uppercase tracking-widest text-muted-foreground">
          Getting started · {index + 1} of {steps.length}
        </p>
        {/* Keyed on the step so the text cross-fades as it changes rather than swapping in place,
            which otherwise reads as a flicker on the fastest connections. */}
        <AnimatePresence mode="wait">
          <motion.div
            key={step.title}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: EASE }}
          >
            <h2 id="onboarding-title" className="mt-1.5 text-sm font-semibold text-foreground">
              {step.title}
            </h2>
            <p id="onboarding-body" className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
              {step.body}
            </p>
          </motion.div>
        </AnimatePresence>

        <div className="mt-4 flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={finish}>
            Skip
          </Button>
          <div className="flex items-center gap-2">
            {index > 0 ? (
              <Button variant="outline" size="sm" onClick={() => setIndex((i) => i - 1)}>
                Back
              </Button>
            ) : null}
            <Button size="sm" onClick={() => (last ? finish() : setIndex((i) => i + 1))}>
              {last ? "Got it" : "Next"}
            </Button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
