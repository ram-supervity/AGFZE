"use client";

import { Menu } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { BrandMark } from "@/components/layout/brand-mark";
import { CommandPalette } from "@/components/layout/command-palette";
import { NotificationBell } from "@/components/layout/notification-bell";
import { UserMenu } from "@/components/layout/user-menu";
import { InstallButton } from "@/components/pwa/install-button";
import { ROLE_LABELS, normaliseRoles, primaryRole, type PlatformRole } from "@/lib/roles";
import { cn } from "@/lib/utils";

export interface AppHeaderProps {
  roles: PlatformRole[];
  userName: string;
  userEmail: string;
  section: string;
  onOpenNav: () => void;
}

const BADGE = "border-border bg-muted text-muted-foreground";

export function AppHeader({ roles, userName, userEmail, section, onOpenNav }: AppHeaderProps) {
  const ordered = normaliseRoles(roles);
  const primary = primaryRole(ordered);
  const extra = ordered.length - 1;

  return (
    <header className="fixed inset-x-0 top-0 z-sticky flex h-14 items-center gap-space-100 border-b border-thin border-border bg-elevation-default px-space-150 text-foreground sm:gap-space-150 sm:px-space-200">
      <Button
        variant="ghost"
        size="icon-md"
        onClick={onOpenNav}
        aria-label="Open navigation"
        className="-ml-1 shrink-0 lg:hidden"
      >
        <Menu aria-hidden="true" />
      </Button>
      <BrandMark variant="compact" className="shrink-0" />
      <Separator orientation="vertical" className="h-space-300 bg-border" />
      <span className="truncate text-body-md font-medium">{section}</span>
      <CommandPalette />
      <div className="ml-auto flex items-center gap-space-100 sm:gap-space-150">
        {primary ? (
          <div className="hidden items-center gap-space-075 sm:flex">
            <Badge variant="outline" className={cn(BADGE, "font-medium")}>
              {ROLE_LABELS[primary]}
            </Badge>
            {extra > 0 ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="outline" tabIndex={0} className={cn(BADGE, "cursor-default")}>
                    +{extra}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent align="end">
                  <ul className="space-y-0.5 text-body-xs">
                    {ordered.map((role) => (
                      <li key={role}>{ROLE_LABELS[role]}</li>
                    ))}
                  </ul>
                </TooltipContent>
              </Tooltip>
            ) : null}
          </div>
        ) : null}
        {/* Shown only where the browser has actually offered an install - Chromium fires
            `beforeinstallprompt`, iOS Safari never does and gets instructions instead, and an
            already-installed app gets nothing. */}
        <InstallButton />
        {/* Deferred explicitly in Steps 1 and 2 for want of anything real to count. It is
            real now: the badge is the API's own unread figure for this account. */}
        <NotificationBell />
        <UserMenu userName={userName} userEmail={userEmail} />
      </div>
    </header>
  );
}
