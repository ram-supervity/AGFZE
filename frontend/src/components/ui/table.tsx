import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Table Header Cell and Table Body Cell are separate in the design system for a reason: the
 * header is not a bolder body row, it is a different thing - it sticks, it labels, and it never
 * carries a value. Keeping them apart here is what lets the header stay pinned at the `sticky`
 * layer while the body scrolls under it.
 */
const Table = React.forwardRef<HTMLTableElement, React.TableHTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => (
    <div className="w-full overflow-x-auto rounded-medium border-thin border-border bg-elevation-default">
      <table ref={ref} className={cn("w-full caption-bottom text-body-md", className)} {...props} />
    </div>
  ),
)
Table.displayName = "Table"

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead
    ref={ref}
    className={cn("bg-elevation-sunken [&_tr]:border-b [&_tr]:border-border", className)}
    {...props}
  />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
))
TableBody.displayName = "TableBody"

const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr
      ref={ref}
      className={cn(
        "border-b border-border transition-colors hover:bg-elevation-hovered data-[state=selected]:bg-background-selected",
        className,
      )}
      {...props}
    />
  ),
)
TableRow.displayName = "TableRow"

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "h-space-500 whitespace-nowrap px-space-150 text-left align-middle text-body-xs font-medium uppercase tracking-widest text-muted-foreground",
      className,
    )}
    {...props}
  />
))
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn("px-space-150 py-space-100 align-middle text-body-md", className)}
    {...props}
  />
))
TableCell.displayName = "TableCell"

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell }
