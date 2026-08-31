import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/**
 * Badge and Tag, on one component.
 *
 * Two families of colour, and they mean different things. The five semantic variants say
 * something about state - this failed, this is waiting, this is fine - and are the only ones
 * allowed to imply urgency. The thirteen hues below them are categorical: a ticket type, a
 * department, an integration. A hue there means "a different kind of thing", never "worse".
 */
const badgeVariants = cva(
  "inline-flex items-center gap-space-075 rounded-control border-thin px-space-100 py-space-050 text-body-sm font-medium transition-colors focus:outline-none focus-visible:ring-thick focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  {
    variants: {
      variant: {
        brand: "border-transparent bg-brand-bold text-text-inverse",
        danger: "border-pill-red-border bg-pill-red-bg text-pill-red-text",
        warning: "border-pill-amber-border bg-pill-amber-bg text-pill-amber-text",
        success: "border-pill-green-border bg-pill-green-bg text-pill-green-text",
        information: "border-pill-blue-border bg-pill-blue-bg text-pill-blue-text",

        purple: "border-pill-purple-border bg-pill-purple-bg text-pill-purple-text",
        pink: "border-pill-pink-border bg-pill-pink-bg text-pill-pink-text",
        blue: "border-pill-blue-border bg-pill-blue-bg text-pill-blue-text",
        sky: "border-pill-sky-border bg-pill-sky-bg text-pill-sky-text",
        red: "border-pill-red-border bg-pill-red-bg text-pill-red-text",
        mint: "border-pill-mint-border bg-pill-mint-bg text-pill-mint-text",
        teal: "border-pill-teal-border bg-pill-teal-bg text-pill-teal-text",
        cyan: "border-pill-cyan-border bg-pill-cyan-bg text-pill-cyan-text",
        rose: "border-pill-rose-border bg-pill-rose-bg text-pill-rose-text",
        amber: "border-pill-amber-border bg-pill-amber-bg text-pill-amber-text",
        green: "border-pill-green-border bg-pill-green-bg text-pill-green-text",
        yellow: "border-pill-yellow-border bg-pill-yellow-bg text-pill-yellow-text",
        orange: "border-pill-orange-border bg-pill-orange-bg text-pill-orange-text",

        // Retained names, resolved onto the same palette.
        default: "border-transparent bg-brand-bold text-text-inverse",
        secondary: "border-transparent bg-information-bold text-text-inverse",
        outline: "border-border text-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
        accent: "border-transparent bg-information-bold text-text-inverse",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, ...props }, ref) => (
    <span ref={ref} className={cn(badgeVariants({ variant }), className)} {...props} />
  ),
)
Badge.displayName = "Badge"

export { Badge, badgeVariants }
