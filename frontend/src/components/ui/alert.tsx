import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * The persistent, inline counterpart to a toast.
 *
 * A toast is a thing that happened and then stops mattering. An alert is a condition that is
 * still true while you read it - an SLA about to breach, a cached figure, a governance notice
 * that has to travel with the screen. So it is never transient and never dismissible by default:
 * it goes away when the condition does.
 *
 * The tint background rather than the bold fill, throughout. A full-strength danger fill on a
 * banner this wide reads as a failure of the page rather than a fact about the record.
 */
const alertVariants = cva(
  "flex items-start gap-space-150 rounded-medium border-thin px-space-200 py-space-150 text-body-md",
  {
    variants: {
      variant: {
        information: "border-pill-blue-border bg-information text-foreground",
        success: "border-pill-green-border bg-success text-foreground",
        warning: "border-pill-amber-border bg-warning text-foreground",
        danger: "border-pill-red-border bg-danger text-foreground",
        neutral: "border-border bg-muted text-foreground",
      },
    },
    defaultVariants: {
      variant: "information",
    },
  },
)

const ICONS: Record<string, LucideIcon> = {
  information: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  danger: CircleAlert,
  neutral: Info,
}

const ICON_TONE: Record<string, string> = {
  information: "text-icon-brand",
  success: "text-icon-success",
  warning: "text-icon-warning",
  danger: "text-icon-danger",
  neutral: "text-icon-subtle",
}

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  /** Overrides the icon the variant would otherwise pick. Pass `null` to draw none. */
  icon?: LucideIcon | null
  /** Trailing slot for a single inline action - never more than one. */
  action?: React.ReactNode
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "information", icon, action, children, role = "note", ...props }, ref) => {
    const key = variant ?? "information"
    const Icon = icon === null ? null : (icon ?? ICONS[key])

    return (
      <div ref={ref} role={role} className={cn(alertVariants({ variant }), className)} {...props}>
        {Icon ? (
          <Icon
            aria-hidden="true"
            className={cn("mt-0.5 size-icon-small shrink-0", ICON_TONE[key])}
          />
        ) : null}
        <div className="min-w-0 flex-1 leading-relaxed">{children}</div>
        {action ? <div className="ml-auto shrink-0">{action}</div> : null}
      </div>
    )
  },
)
Alert.displayName = "Alert"

const AlertTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn("font-semibold text-foreground", className)} {...props} />
  ),
)
AlertTitle.displayName = "AlertTitle"

const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p ref={ref} className={cn("leading-relaxed text-foreground", className)} {...props} />
))
AlertDescription.displayName = "AlertDescription"

export { Alert, AlertTitle, AlertDescription, alertVariants }
