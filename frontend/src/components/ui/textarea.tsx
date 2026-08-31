import * as React from "react"

import { cn } from "@/lib/utils"

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, rows = 3, ...props }, ref) => (
  <textarea
    ref={ref}
    rows={rows}
    className={cn(
      "flex w-full rounded-control border-thin border-border bg-background-input px-space-150 py-space-100 text-body-md text-foreground transition-colors placeholder:text-muted-foreground hover:border-border-bold focus-visible:border-border-brand focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-disabled aria-[invalid=true]:border-border-danger",
      className,
    )}
    {...props}
  />
))
Textarea.displayName = "Textarea"

export { Textarea }
