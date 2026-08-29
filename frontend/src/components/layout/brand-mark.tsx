import { cn } from "@/lib/utils";

const COPPER = "#A75D35";

export interface BrandMarkProps {
  variant?: "full" | "compact";
  className?: string;
}

export function BrandMark({ variant = "full", className }: BrandMarkProps) {
  const compact = variant === "compact";

  return (
    <span className={cn("inline-flex items-center gap-2.5 text-current", className)}>
      <svg
        viewBox="0 0 32 32"
        aria-hidden="true"
        className={cn("shrink-0", compact ? "h-7 w-7" : "h-9 w-9")}
      >
        <rect width="32" height="32" rx="7" fill="currentColor" />
        <path d="M13.5 9h5l2.5 4H11z" fill={COPPER} />
        <path d="M11.5 14.5h9l2.5 4H9z" fill={COPPER} fillOpacity="0.85" />
        <path d="M9.5 20h13l2.5 4H7z" fill={COPPER} fillOpacity="0.7" />
      </svg>
      <span className="flex flex-col justify-center leading-none">
        <span className={cn("font-semibold tracking-[0.18em]", compact ? "text-sm" : "text-base")}>
          AGFZE
        </span>
        {!compact ? (
          <span className="mt-1.5 text-[10px] uppercase tracking-[0.22em] opacity-70">
            Command Centre
          </span>
        ) : null}
      </span>
    </span>
  );
}
