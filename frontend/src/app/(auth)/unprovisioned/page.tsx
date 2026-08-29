import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Access not assigned yet" };

export default async function UnprovisionedPage() {
  const session = await getServerAuthSession();
  if (!session) redirect("/signin");

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="text-xl">Your access isn’t set up yet</CardTitle>
          <CardDescription>
            Sign-in worked. Your account simply has no AGFZE Command Centre role on it so far.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm leading-7 text-muted-foreground">
          <p>
            You are signed in as{" "}
            <span className="font-medium text-foreground">
              {session.user.email ?? "an account with no email address on record"}
            </span>
            . Roles decide which parts of the platform open for you, and yours has not been assigned
            yet, so there is nothing here to show.
          </p>
          <p>
            A platform administrator assigns roles. Ask yours to add the role your work requires —
            they will already know which one that is from your team. Once it is in place, select
            “Check again” below.
          </p>
        </CardContent>
        <CardFooter className="flex flex-wrap gap-3">
          <Button asChild>
            <Link href="/dashboard">Check again</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/signout">Sign out</Link>
          </Button>
        </CardFooter>
      </Card>
    </main>
  );
}
