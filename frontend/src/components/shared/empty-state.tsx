import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  /** One recovery action at most, and only where there genuinely is one. */
  action?: ReactNode;
  className?: string;
}

/**
 * Icon, heading, a sentence, and at most one way forward - the CCDS empty-state anatomy, at the
 * 48px container / 20px glyph the design system draws it at. A queue with nothing in it and a
 * screen that failed to load look identical without this, and only one of them is good news.
 */
export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-medium border-thin border-dashed border-border bg-elevation-sunken px-space-300 py-space-600 text-center",
        className,
      )}
    >
      <span className="mb-space-200 flex size-space-600 items-center justify-center rounded-medium bg-muted text-icon-subtle">
        <Icon className="size-icon-medium" aria-hidden="true" />
      </span>
      <p className="text-body-md font-medium text-foreground">{title}</p>
      <p className="mt-space-050 max-w-md text-body-md leading-relaxed text-muted-foreground">
        {description}
      </p>
      {action ? <div className="mt-space-250">{action}</div> : null}
    </div>
  );
}
