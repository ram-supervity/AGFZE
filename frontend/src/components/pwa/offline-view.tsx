"use client";

import { CloudOff, FileText, Loader2, Wifi } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/layout/brand-mark";
import { Button } from "@/components/ui/button";

/**
 * What is honestly available with no connection, and what is honestly not.
 *
 * The second list is the important one. Every action this platform governs - submitting,
 * approving, generating a draft, correcting a field - needs the server, and none of them is
 * queued for later: an approval decision replayed from a pocket three hours later, against a
 * record that has since moved on, is a governance failure rather than a convenience. So this page
 * says plainly that those actions are unavailable rather than letting somebody try one.
 */
const STILL_AVAILABLE = [
  "Screens you have already opened in this session — queues, transactions, exceptions, shipments",
  "The detail of any record whose page you have visited recently",
  "Your notification list as it stood when the connection dropped",
];

const NEEDS_A_CONNECTION = [
  "Submitting a transaction, or deciding an approval",
  "Generating a draft document, confirming a document, or resolving an exception",
  "Correcting an extracted field, or anything else that changes a record",
];

export function OfflineView() {
  const [online, setOnline] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    setChecking(false);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);

    // A poll as well as the events: `online` fires when the interface comes back, which is not
    // quite the same as the network being usable again, and this page should notice either way.
    const timer = window.setInterval(update, 5_000);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
      window.clearInterval(timer);
    };
  }, []);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-2xl flex-col justify-center gap-6 px-6 py-12">
      <BrandMark className="text-primary" />

      <div className="rounded-lg border border-border bg-surface p-6">
        <div className="flex items-start gap-3">
          <CloudOff aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
          <div>
            <h1 className="text-lg font-semibold text-foreground">You&rsquo;re offline</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              This device has no connection to the Command Centre. Nothing has been lost — the
              platform&rsquo;s record is on the server, and this browser has not changed any of it.
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <section>
            <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <FileText aria-hidden="true" className="h-3.5 w-3.5" />
              Still readable
            </h2>
            <ul className="mt-2 space-y-1.5 text-sm text-foreground">
              {STILL_AVAILABLE.map((item) => (
                <li key={item} className="leading-snug">
                  {item}
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Needs a connection
            </h2>
            <ul className="mt-2 space-y-1.5 text-sm text-foreground">
              {NEEDS_A_CONNECTION.map((item) => (
                <li key={item} className="leading-snug">
                  {item}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              None of these is saved up and sent later. Nothing you do offline is queued, so
              nothing can be applied hours afterwards against a record that has moved on.
            </p>
          </section>
        </div>

        <div
          role="status"
          aria-live="polite"
          className="mt-6 flex flex-wrap items-center gap-3 rounded-md border border-border bg-background px-3.5 py-2.5"
        >
          {online ? (
            <>
              <Wifi aria-hidden="true" className="h-4 w-4 text-signal-confident" />
              <span className="text-sm text-foreground">
                You&rsquo;re back online.
              </span>
              <Button size="sm" asChild className="ml-auto">
                <Link href="/dashboard">Continue</Link>
              </Button>
            </>
          ) : (
            <>
              <Loader2
                aria-hidden="true"
                className={`h-4 w-4 text-muted-foreground ${checking ? "" : "animate-spin"}`}
              />
              <span className="text-sm text-muted-foreground">
                Watching for the connection to come back. This page will say so the moment it
                does — there is nothing to refresh.
              </span>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
