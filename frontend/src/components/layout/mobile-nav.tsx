"use client";

import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { BrandMark } from "@/components/layout/brand-mark";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { visibleNavItems } from "@/lib/navigation";
import type { PlatformRole } from "@/lib/roles";

export interface MobileNavProps {
  roles: PlatformRole[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MobileNav({ roles, open, onOpenChange }: MobileNavProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="left"
        className="w-72 gap-0 border-sidebar-border bg-sidebar text-sidebar-foreground [&>button]:text-sidebar-foreground"
      >
        <SheetTitle className="sr-only">AGFZE Command Centre navigation</SheetTitle>
        <SheetDescription className="sr-only">
          Modules available to your role, and the ones still to come.
        </SheetDescription>
        <div className="border-b border-sidebar-border px-4 py-4">
          <BrandMark variant="full" />
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <SidebarNav
            items={visibleNavItems(roles)}
            roles={roles}
            collapsed={false}
            onNavigate={() => onOpenChange(false)}
            className="p-3"
          />
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
