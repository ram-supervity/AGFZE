import * as React from "react"

import { cn } from "@/lib/utils"

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value: number
  label?: string
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value, label, ...props }, ref) => {
    const clamped = Math.max(0, Math.min(100, Math.round(value)))
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={clamped}
        aria-label={label}
        className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
        {...props}
      >
        <div
          className="h-full rounded-full bg-brand-bold transition-[width] duration-slow ease-linear"
          style={{ width: `${clamped}%` }}
        />
      </div>
    )
  },
)
Progress.displayName = "Progress"

export { Progress }
