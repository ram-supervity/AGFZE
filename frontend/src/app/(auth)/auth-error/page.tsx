"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface AuthErrorCopy {
  title: string;
  description: string;
  detail: string;
}

const DEFAULT_COPY: AuthErrorCopy = {
  title: "We couldn’t complete your sign-in",
  description: "Something interrupted the exchange with the identity provider.",
  detail:
    "This is usually temporary. Start the sign-in again, and if it keeps failing, contact the IT service desk.",
};

const AUTH_ERROR_COPY: Record<string, AuthErrorCopy> = {
  Configuration: {
    title: "Sign-in isn’t configured here",
    description: "This environment is missing part of its identity configuration.",
    detail:
      "Nothing you can do will fix this from your side. Please contact a platform administrator so the environment can be corrected.",
  },
  AccessDenied: {
    title: "The identity provider declined this sign-in",
    description: "Your account was not permitted to continue into the platform.",
    detail:
      "Your account may not be entitled to use AGFZE Command Centre yet. Contact a platform administrator to confirm your access.",
  },
  Verification: {
    title: "That sign-in link is no longer valid",
    description: "The link had already been used, or it expired before it was opened.",
    detail: "Start the sign-in again from the sign-in page to get a fresh one.",
  },
  OAuthSignin: {
    title: "We couldn’t reach the identity provider",
    description: "The sign-in request could not be started.",
    detail:
      "The identity provider may be briefly unavailable. Wait a moment and try again; if it persists, contact the IT service desk.",
  },
  OAuthCallback: {
    title: "The sign-in response couldn’t be validated",
    description: "The reply from the identity provider did not check out.",
    detail:
      "This can happen if the sign-in took too long or was opened in more than one tab. Please try again in a single tab.",
  },
  OAuthCreateAccount: {
    title: "Your account couldn’t be set up",
    description: "The platform was unable to create a record for your account.",
    detail: "Please contact a platform administrator so your account can be provisioned.",
  },
  OAuthAccountNotLinked: {
    title: "This account is already linked another way",
    description: "The identity used here doesn’t match the one already on record.",
    detail:
      "Sign in with the account you normally use for AGFZE systems, or ask a platform administrator to reconcile the two.",
  },
  Callback: {
    title: "The sign-in couldn’t be finished",
    description: "The final  of the sign-in did not complete.",
    detail: "Please start again from the sign-in page.",
  },
  SessionRequired: {
    title: "You need to be signed in",
    description: "That page is only available to a signed-in account.",
    detail: "Sign in and you will be taken to where you were heading.",
  },
};

function AuthErrorContent() {
  const searchParams = useSearchParams();
  const code = searchParams.get("error");
  const copy = (code ? AUTH_ERROR_COPY[code] : undefined) ?? DEFAULT_COPY;

  return (
    <Card className="w-full max-w-lg">
      <CardHeader>
        <CardTitle className="text-xl">{copy.title}</CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-7 text-muted-foreground">{copy.detail}</p>
      </CardContent>
      <CardFooter>
        <Button asChild>
          <Link href="/signin">Try again</Link>
        </Button>
      </CardFooter>
    </Card>
  );
}

export default function AuthErrorPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <Suspense fallback={<Skeleton className="h-64 w-full max-w-lg" />}>
        <AuthErrorContent />
      </Suspense>
    </main>
  );
}
