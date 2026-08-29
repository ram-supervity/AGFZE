import Link from "next/link";

import { BrandMark } from "@/components/layout/brand-mark";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 bg-surface px-6 py-16">
      <BrandMark variant="full" />
      <div className="max-w-md space-y-3 text-center">
        <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
          Page not found
        </p>
        <h1 className="text-2xl font-semibold text-foreground">This address doesn’t lead anywhere</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          The page you asked for isn’t part of AGFZE Command Centre, or it belongs to a module that
          has not been released yet. Check the link you followed, or go back to a page you can open.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button asChild>
          <Link href="/dashboard">Go to dashboard</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/signin">Go to sign in</Link>
        </Button>
      </div>
    </main>
  );
}
