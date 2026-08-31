"use client";

import { ChevronsLeft } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { visibleNavItems } from "@/lib/navigation";
import type { PlatformRole } from "@/lib/roles";
import { cn } from "@/lib/utils";

export interface AppSidebarProps {
  roles: PlatformRole[];
  collapsed: boolean;
  onToggle: () => void;
  className?: string;
}

export function AppSidebar({ roles, collapsed, onToggle, className }: AppSidebarProps) {
  return (
    <aside
      className={cn(
        "fixed bottom-0 left-0 top-14 z-raised flex flex-col border-r border-thin border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-medium",
        collapsed ? "w-16" : "w-64",
        className,
      )}
    >
      <ScrollArea className="min-h-0 flex-1">
        <SidebarNav
          items={visibleNavItems(roles)}
          roles={roles}
          collapsed={collapsed}
          className={collapsed ? "p-space-100" : "p-space-150"}
        />
      </ScrollArea>
      <div className="border-t border-thin border-sidebar-border p-space-100">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className={cn(
            "flex h-control-md w-full items-center rounded-control text-body-md text-sidebar-muted transition-colors hover:bg-sidebar-border/50 hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-sidebar-active",
            collapsed ? "justify-center px-0" : "gap-space-150 px-space-150",
          )}
        >
          <ChevronsLeft
            className={cn("size-icon-small shrink-0 transition-transform", collapsed && "rotate-180")}
            aria-hidden="true"
          />
          {collapsed ? null : <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
