import type { ReactNode } from "react";

export interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-space-150 border-b border-thin border-border pb-space-250 sm:flex-row sm:items-start sm:justify-between sm:gap-space-300">
      <div className="min-w-0 space-y-space-050">
        <h1 className="text-h2 font-semibold tracking-tight text-foreground">{title}</h1>
        {description ? (
          <p className="max-w-2xl text-body-md leading-relaxed text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-space-100">{actions}</div> : null}
    </div>
  );
}
