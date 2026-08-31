import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/**
 * The CCDS Button.
 *
 * Four styles, five sizes, five content arrangements - and the five states are left to the
 * browser rather than modelled as a prop, because hover, press and focus are the user's to
 * decide and only `disabled` is ours. Hover and press are the opacity-overlay mechanism the
 * design system recommends for anything new: one tint, composed over whatever fill the style
 * already has, so a new style never needs a hand-picked hover colour.
 *
 * `primary` is the brand gradient and there is at most one of it per view. `ai` is the same
 * gradient poured into the glyphs instead - reserved for AI-forward actions, nothing else.
 */
const buttonVariants = cva(
  "relative inline-flex items-center justify-center gap-space-075 whitespace-nowrap rounded-control font-medium transition-colors after:pointer-events-none after:absolute after:inset-0 after:rounded-control after:bg-foreground after:opacity-0 after:transition-opacity hover:after:opacity-hover active:after:opacity-pressed focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-disabled disabled:after:opacity-0 [&_svg]:pointer-events-none [&_svg]:size-icon-small [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-brand-gradient text-text-inverse",
        secondary: "bg-information-bold text-text-inverse",
        tertiary: "border-thin border-border bg-muted text-foreground",
        danger: "bg-danger-bold text-text-inverse",
        ai: "border-thin border-brand-bold bg-transparent text-brand-gradient",
        ghost: "text-foreground",
        link: "text-text-link underline-offset-4 after:hidden hover:underline",
        // Retained names, pointed at the style the design system defines for that intent, so
        // there is one button and not two.
        default: "bg-brand-gradient text-text-inverse",
        outline: "border-thin border-border bg-muted text-foreground",
        accent: "bg-information-bold text-text-inverse",
        destructive: "bg-danger-bold text-text-inverse",
      },
      size: {
        xs: "h-6 px-space-100 text-body-sm",
        sm: "h-[26px] px-space-150 text-body-sm",
        md: "h-8 px-space-200 text-label-lg",
        lg: "h-[38px] px-space-250 text-label-lg",
        xl: "h-[42px] px-space-300 text-label-lg",
        "icon-xs": "h-5 w-5",
        "icon-sm": "h-[26px] w-[26px]",
        "icon-md": "h-control-md w-control-md",
        "icon-lg": "h-control-lg w-control-lg",
        "icon-xl": "h-12 w-12",
        default: "h-8 px-space-200 text-label-lg",
        icon: "h-control-md w-control-md",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type = "button", ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    const buttonProps = asChild ? props : { type, ...props }
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size, className }))}
        {...buttonProps}
      />
    )
  },
)
Button.displayName = "Button"

export { Button, buttonVariants }
