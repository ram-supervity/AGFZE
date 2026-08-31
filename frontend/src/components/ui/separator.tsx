"use client"

import * as React from "react"
import * as SeparatorPrimitive from "@radix-ui/react-separator"

import { cn } from "@/lib/utils"

export type SeparatorVariant = "default" | "bold" | "subtle" | "dashed" | "gradient"

export interface SeparatorProps
  extends React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root> {
  variant?: SeparatorVariant
  /** Renders the rule interrupted by a centred label, for naming a section inside one panel. */
  label?: React.ReactNode
}

const RULE: Record<SeparatorVariant, string> = {
  default: "bg-border",
  bold: "bg-border-bold",
  subtle: "bg-border/50",
  dashed: "border-t border-dashed border-border bg-transparent",
  gradient: "bg-gradient-to-r from-transparent via-border-bold to-transparent",
}

const Separator = React.forwardRef<
  React.ElementRef<typeof SeparatorPrimitive.Root>,
  SeparatorProps
>(
  (
    { className, orientation = "horizontal", decorative = true, variant = "default", label, ...props },
    ref,
  ) => {
    const rule = cn(
      "shrink-0",
      RULE[variant],
      variant === "dashed" ? "h-0" : orientation === "horizontal" ? "h-px" : "h-full w-px",
      orientation === "horizontal" ? "w-full" : "w-px",
    )

    if (label && orientation === "horizontal") {
      return (
        <div className={cn("flex items-center gap-space-150", className)}>
          <span aria-hidden="true" className={rule} />
          <span className="shrink-0 text-body-xs font-medium uppercase tracking-widest text-muted-foreground">
            {label}
          </span>
          <span aria-hidden="true" className={rule} />
        </div>
      )
    }

    return (
      <SeparatorPrimitive.Root
        ref={ref}
        decorative={decorative}
        orientation={orientation}
        className={cn(rule, className)}
        {...props}
      />
    )
  },
)
Separator.displayName = SeparatorPrimitive.Root.displayName

export { Separator }
