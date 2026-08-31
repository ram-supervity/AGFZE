import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * A loading placeholder at `Opacity/loading`. Size it to the component it stands in for, so the
 * layout does not jump when the real content lands.
 */
const Skeleton = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      aria-hidden="true"
      className={cn("animate-pulse rounded-control bg-muted opacity-loading", className)}
      {...props}
    />
  ),
)
Skeleton.displayName = "Skeleton"

export { Skeleton }
