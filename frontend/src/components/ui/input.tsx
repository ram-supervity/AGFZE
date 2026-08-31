import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      aria-invalid={props["aria-invalid"]}
      className={cn(
        "flex h-control-md w-full rounded-control border-thin border-border bg-background-input px-space-150 text-body-md text-foreground transition-colors file:border-0 file:bg-transparent file:text-body-md file:font-medium placeholder:text-muted-foreground hover:border-border-bold focus-visible:border-border-brand focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-disabled aria-[invalid=true]:border-border-danger",
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = "Input"

export { Input }
