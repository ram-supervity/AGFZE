import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface LegalPageProps {
  title: string;
  version: string;
  effectiveNote: string;
  children: ReactNode;
}

const PROSE = cn(
  "mt-8 text-[15px] text-foreground [&>*+*]:mt-4",
  "[&_section]:space-y-3",
  "[&_h2]:mt-10 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:tracking-tight [&_h2]:text-foreground",
  "[&_h3]:mt-6 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:uppercase [&_h3]:tracking-[0.14em] [&_h3]:text-muted-foreground",
  "[&_p]:leading-relaxed [&_p]:text-muted-foreground",
  "[&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-5",
  "[&_ol]:list-decimal [&_ol]:space-y-2 [&_ol]:pl-5",
  "[&_li]:leading-relaxed [&_li]:text-muted-foreground [&_li]:marker:text-accent",
  "[&_strong]:font-semibold [&_strong]:text-foreground",
  "[&_a]:font-medium [&_a]:text-accent [&_a]:underline [&_a]:underline-offset-4",
);

export function LegalPage({ title, version, effectiveNote, children }: LegalPageProps) {
  const versionLabel = version.replace(/^version\s+/i, "");

  return (
    <article className="mx-auto w-full max-w-3xl">
      <header className="border-b border-border pb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          {title}
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Version {versionLabel} - {effectiveNote}
        </p>
      </header>
      <div className={PROSE}>{children}</div>
    </article>
  );
}
