import * as React from "react"
import { ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * A styled native <select>. The platform control brings keyboard behaviour, screen-reader
 * semantics and mobile pickers for free, which a custom listbox would have to re-earn. Its shell
 * is the Input's, deliberately: a select and a text field are the same control height, radius and
 * border in this system, and only the trailing chevron tells them apart.
 */
const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          "h-control-md w-full appearance-none rounded-control border-thin border-border bg-background-input pl-space-150 pr-space-400 text-body-md text-foreground transition-colors hover:border-border-bold focus-visible:border-border-brand focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-disabled",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute right-space-100 top-1/2 size-icon-small -translate-y-1/2 text-icon-subtle"
      />
    </div>
  ),
)
Select.displayName = "Select"

export { Select }
