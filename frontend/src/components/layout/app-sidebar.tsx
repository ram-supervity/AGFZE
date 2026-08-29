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
        "fixed bottom-0 left-0 top-14 z-30 flex flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200",
        collapsed ? "w-16" : "w-64",
        className,
      )}
    >
      <ScrollArea className="min-h-0 flex-1">
        <SidebarNav
          items={visibleNavItems(roles)}
          roles={roles}
          collapsed={collapsed}
          className={collapsed ? "p-2" : "p-3"}
        />
      </ScrollArea>
      <div className="border-t border-sidebar-border p-2">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className={cn(
            "flex h-9 w-full items-center rounded-md text-sm text-sidebar-muted transition-colors hover:bg-sidebar-border/50 hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-active",
            collapsed ? "justify-center px-0" : "gap-3 px-3",
          )}
        >
          <ChevronsLeft
            className={cn("h-4 w-4 shrink-0 transition-transform", collapsed && "rotate-180")}
            aria-hidden="true"
          />
          {collapsed ? null : <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
