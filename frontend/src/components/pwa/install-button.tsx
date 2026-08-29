"use client";

import { Download, Share } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { isIosSafari, isStandalone, type BeforeInstallPromptEvent } from "@/lib/pwa";

/**
 * The install affordance, and the two quite different things it has to be.
 *
 * On Chromium - Android, Windows, macOS - the browser fires `beforeinstallprompt`, the event is
 * kept, and clicking the button opens the browser's own native install dialog. On iOS Safari that
 * event does not exist and never will, and there is no API that can install anything: the only
 * route is the Share sheet. So on iOS the same button opens a short set of instructions instead
 * of pretending to do something it cannot do.
 *
 * The button is absent entirely where neither applies - already installed, or a browser with no
 * install concept at all - because a control that does nothing is worse than no control.
 */
export function InstallButton() {
  const [promptEvent, setPromptEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [showIosHelp, setShowIosHelp] = useState(false);
  const [ios, setIos] = useState(false);
  const [installed, setInstalled] = useState(true);

  useEffect(() => {
    setInstalled(isStandalone());
    setIos(isIosSafari());

    const onPrompt = (event: Event) => {
      // Chromium shows its own affordance unless the event is prevented; this is where that is
      // taken over so the install lives in the application header beside everything else.
      event.preventDefault();
      setPromptEvent(event as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setPromptEvent(null);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (installed) return null;
  if (!promptEvent && !ios) return null;

  async function install() {
    if (ios && !promptEvent) {
      setShowIosHelp(true);
      return;
    }
    if (!promptEvent) return;
    await promptEvent.prompt();
    const choice = await promptEvent.userChoice;
    // The event is single-use whatever the answer was; the browser fires a fresh one if the user
    // becomes eligible again.
    setPromptEvent(null);
    if (choice.outcome === "accepted") setInstalled(true);
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => void install()}
        aria-label="Install the Command Centre on this device"
        className="hidden h-9 gap-1.5 px-2.5 text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground sm:inline-flex"
      >
        <Download aria-hidden="true" className="h-[18px] w-[18px]" />
        <span className="text-xs font-medium">Install</span>
      </Button>

      <Dialog open={showIosHelp} onOpenChange={setShowIosHelp}>
        <DialogContent className="max-w-sm">
          <div className="space-y-1.5">
            <DialogTitle>Add to your Home Screen</DialogTitle>
            <DialogDescription>
              Safari installs an app from the Share sheet rather than from a prompt, so this one
              takes two taps.
            </DialogDescription>
          </div>
          <ol className="space-y-2.5 text-sm text-foreground">
            <li className="flex items-start gap-2.5">
              <Share aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
              <span>
                Tap <span className="font-medium">Share</span> in Safari&rsquo;s toolbar.
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <span
                aria-hidden="true"
                className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border border-accent text-[11px] font-semibold leading-none text-accent"
              >
                +
              </span>
              <span>
                Choose <span className="font-medium">Add to Home Screen</span>, then{" "}
                <span className="font-medium">Add</span>.
              </span>
            </li>
          </ol>
          <p className="text-xs text-muted-foreground">
            You will still be asked to sign in, exactly as you are in the browser. Nothing is
            stored on the device that is not already cached by Safari.
          </p>
        </DialogContent>
      </Dialog>
    </>
  );
}
