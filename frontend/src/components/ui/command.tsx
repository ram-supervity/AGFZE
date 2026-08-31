"use client"

import * as React from "react"
import { Command as CommandPrimitive } from "cmdk"
import { Search } from "lucide-react"

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

/**
 * A thin, styled wrapper around cmdk, in the same shape as the Radix wrappers beside it.
 *
 * cmdk owns the behaviour that is genuinely hard to get right - filtering, the active-descendant
 * bookkeeping that keeps a screen reader told which option is current, and arrow-key navigation
 * through a list that changes under the cursor. Reimplementing that would mean reimplementing the
 * accessibility with it.
 */
const Command = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
  <CommandPrimitive
    ref={ref}
    className={cn(
      "flex h-full w-full flex-col overflow-hidden rounded-medium bg-elevation-overlay text-foreground",
      className,
    )}
    {...props}
  />
))
Command.displayName = CommandPrimitive.displayName

/**
 * The palette in a dialog. Escape-to-close and the focus trap come from the Radix dialog the rest
 * of this application already uses, rather than from a second implementation of both.
 */
function CommandDialog({
  open,
  onOpenChange,
  label,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  label: string
  children: React.ReactNode
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 sm:max-w-xl">
        {/* Present for the accessible name and deliberately not drawn: a palette that announced a
            heading above its own input would read oddly, but one with no name at all is worse. */}
        <DialogTitle className="sr-only">{label}</DialogTitle>
        <DialogDescription className="sr-only">
          Type to search, use the arrow keys to move through results, Enter to open one and Escape
          to close.
        </DialogDescription>
        <Command shouldFilter={false}>{children}</Command>
      </DialogContent>
    </Dialog>
  )
}

const CommandInput = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="flex items-center gap-space-100 border-b border-thin border-border px-space-150">
    <Search className="size-icon-small shrink-0 text-icon-subtle" aria-hidden="true" />
    <CommandPrimitive.Input
      ref={ref}
      className={cn(
        "h-control-lg w-full bg-transparent py-space-150 text-body-md outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-disabled",
        className,
      )}
      {...props}
    />
  </div>
))
CommandInput.displayName = CommandPrimitive.Input.displayName

const CommandList = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.List
    ref={ref}
    className={cn("max-h-80 overflow-y-auto overflow-x-hidden p-space-050", className)}
    {...props}
  />
))
CommandList.displayName = CommandPrimitive.List.displayName

const CommandEmpty = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Empty>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>((props, ref) => (
  <CommandPrimitive.Empty
    ref={ref}
    className="px-space-150 py-space-300 text-center text-body-md text-muted-foreground"
    {...props}
  />
))
CommandEmpty.displayName = CommandPrimitive.Empty.displayName

const CommandGroup = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Group>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Group
    ref={ref}
    className={cn(
      "overflow-hidden p-space-050 text-foreground [&_[cmdk-group-heading]]:px-space-100 [&_[cmdk-group-heading]]:py-space-075 [&_[cmdk-group-heading]]:text-body-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-muted-foreground",
      className,
    )}
    {...props}
  />
))
CommandGroup.displayName = CommandPrimitive.Group.displayName

const CommandItem = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex cursor-pointer select-none items-center gap-space-100 rounded-control px-space-100 py-space-100 text-body-md outline-none data-[disabled=true]:pointer-events-none data-[selected=true]:bg-elevation-overlay-hovered data-[disabled=true]:opacity-disabled",
      className,
    )}
    {...props}
  />
))
CommandItem.displayName = CommandPrimitive.Item.displayName

export {
  Command,
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
}
