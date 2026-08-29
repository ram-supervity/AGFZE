"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, type ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ComingSoonBadge } from "@/components/shared/coming-soon-badge";
import { visibleNavChildren, type NavChild, type NavItem } from "@/lib/navigation";
import type { PlatformRole } from "@/lib/roles";
import { cn } from "@/lib/utils";

export interface SidebarNavProps {
  items: NavItem[];
  collapsed: boolean;
  /** Decides which live screens inside a section this account may actually open. */
  roles?: PlatformRole[];
  onNavigate?: () => void;
  className?: string;
}

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

const ROW = "relative flex h-9 items-center rounded-md text-sm transition-colors";

export function SidebarNav({
  items,
  collapsed,
  roles = [],
  onNavigate,
  className,
}: SidebarNavProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary" className={cn("flex flex-col gap-1", className)}>
      {items.map((item) => {
        const Icon = item.icon;
        const active = item.status === "available" && isActive(pathname, item.href);
        const spacing = collapsed ? "justify-center px-0" : "gap-3 px-3";

        const row =
          item.status === "available" ? (
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                ROW,
                spacing,
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-active",
                active
                  ? "bg-sidebar-border/70 font-medium text-sidebar-foreground"
                  : "text-sidebar-foreground/85 hover:bg-sidebar-border/50 hover:text-sidebar-foreground",
              )}
            >
              {active ? (
                <span
                  aria-hidden="true"
                  className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-sidebar-active"
                />
              ) : null}
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {collapsed ? null : <span className="truncate">{item.label}</span>}
            </Link>
          ) : (
            <div
              aria-disabled="true"
              tabIndex={-1}
              className={cn(ROW, spacing, "cursor-default text-sidebar-muted")}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {collapsed ? null : (
                <>
                  <span className="truncate">{item.label}</span>
                  <ComingSoonBadge className="ml-auto border-sidebar-border bg-transparent text-sidebar-muted" />
                </>
              )}
            </div>
          );

        // A section that is otherwise still to come may already hold one live screen. The
        // Integration monitor is the first: Admin as a whole arrives later, so its own row stays
        // disabled while the screen underneath it is a real link.
        const children = visibleNavChildren(item, roles);
        const nested =
          children.length > 0 && !collapsed ? (
            <ul className="mt-0.5 space-y-0.5 border-l border-sidebar-border pl-3">
              {children.map((child) => (
                <li key={child.key}>
                  <ChildRow
                    child={child}
                    active={isActive(pathname, child.href)}
                    onNavigate={onNavigate}
                  />
                </li>
              ))}
            </ul>
          ) : null;

        const tip = tooltipFor(item, collapsed);
        if (!tip) {
          return (
            <Fragment key={item.key}>
              {row}
              {nested}
            </Fragment>
          );
        }

        return (
          <Fragment key={item.key}>
            <Tooltip>
              <TooltipTrigger asChild>{row}</TooltipTrigger>
              <TooltipContent side="right" align="center" className="max-w-[15rem]">
                {tip}
              </TooltipContent>
            </Tooltip>
            {nested}
          </Fragment>
        );
      })}
    </nav>
  );
}

function ChildRow({
  child,
  active,
  onNavigate,
}: {
  child: NavChild;
  active: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={child.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      title={child.summary}
      className={cn(
        "flex h-8 items-center rounded-md px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-active",
        active
          ? "bg-sidebar-border/70 font-medium text-sidebar-foreground"
          : "text-sidebar-foreground/75 hover:bg-sidebar-border/50 hover:text-sidebar-foreground",
      )}
    >
      <span className="truncate">{child.label}</span>
    </Link>
  );
}


function tooltipFor(item: NavItem, collapsed: boolean): ReactNode {
  if (item.status === "available") {
    return collapsed ? item.label : null;
  }

  return (
    <div className="space-y-1">
      {collapsed ? <p className="font-medium">{item.label}</p> : null}
      <p className="text-xs leading-relaxed">{item.summary}</p>
      {item.availableFrom ? (
        <p className="text-xs opacity-80">Arrives in {item.availableFrom}</p>
      ) : null}
    </div>
  );
}
