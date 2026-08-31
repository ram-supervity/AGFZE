"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AppHeader } from "@/components/layout/app-header";
import { OnboardingWalkthrough } from "@/components/shared/onboarding-walkthrough";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { MobileNav } from "@/components/layout/mobile-nav";
import { OfflineBanner } from "@/components/pwa/offline-banner";
import { PushPrompt } from "@/components/pwa/push-prompt";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useSessionRefresh } from "@/hooks/use-session-refresh";
import { NAV_ITEMS } from "@/lib/navigation";
import type { PlatformRole } from "@/lib/roles";
import { cn } from "@/lib/utils";

export interface AppShellProps {
  roles: PlatformRole[];
  /** Server-owned, so the tour cannot reappear on a second device or a cleared cache. */
  onboardingCompleted: boolean;
  userName: string;
  userEmail: string;
  children: ReactNode;
}

function sectionLabel(pathname: string): string {
  const matches = NAV_ITEMS.filter(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  );
  const deepest = matches.sort((a, b) => b.href.length - a.href.length)[0];
  return deepest ? deepest.label : "Command Centre";
}

export function AppShell({
  roles,
  userName,
  userEmail,
  onboardingCompleted,
  children,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  useSessionRefresh();

  useEffect(() => {
    if (isDesktop) setMobileOpen(false);
  }, [isDesktop]);

  return (
    <TooltipProvider delayDuration={150}>
      <div className="min-h-screen bg-background">
        <AppHeader
          roles={roles}
          userName={userName}
          userEmail={userEmail}
          section={sectionLabel(pathname)}
          onOpenNav={() => setMobileOpen(true)}
        />
        <AppSidebar
          roles={roles}
          collapsed={collapsed}
          onToggle={() => setCollapsed((value) => !value)}
          className="hidden lg:flex"
        />
        <MobileNav roles={roles} open={mobileOpen} onOpenChange={setMobileOpen} />
        <main
          className={cn(
            "pt-14 transition-[padding] duration-medium",
            collapsed ? "lg:pl-16" : "lg:pl-64",
          )}
        >
          <div className="mx-auto w-full max-w-7xl px-space-200 py-space-300 md:px-space-300 lg:px-space-400 xl:px-space-500">
            {/* Both render nothing at all in the ordinary case: the banner only when the
                connection is gone or the data on screen came out of the cache, and the prompt
                only once work has actually reached this person - never on page load. */}
            <OfflineBanner />
            <PushPrompt />
            <OnboardingWalkthrough roles={roles} completed={onboardingCompleted} />
            {children}
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
