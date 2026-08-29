"use client";

import { Loader2, LogIn } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { Suspense, useState } from "react";

import { BrandMark } from "@/components/layout/brand-mark";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const SIGN_IN_ERRORS: Record<string, string> = {
  OAuthSignin: "We couldn’t start the sign-in request with the identity provider. Please try again.",
  OAuthCallback:
    "The identity provider’s response couldn’t be validated. Please start the sign-in again.",
  OAuthCreateAccount:
    "Your account couldn’t be set up on this platform. Please contact a platform administrator.",
  Callback: "The sign-in couldn’t be completed. Please try again.",
  AccessDenied:
    "The identity provider declined this sign-in. Your account may not be permitted to use this platform.",
  Configuration:
    "Sign-in is not configured correctly in this environment. Please contact a platform administrator.",
  Verification: "That sign-in link is no longer valid. Please start again.",
  SessionExpired: "Your session expired and you were signed out. Please sign in again to continue.",
  default: "We couldn’t sign you in. Please try again.",
};

const LEGAL_LINKS = [
  { href: "/disclaimer", label: "Disclaimer" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
] as const;

function SignInForm() {
  const searchParams = useSearchParams();
  const [redirecting, setRedirecting] = useState(false);

  const callbackUrl = searchParams.get("callbackUrl") ?? "/dashboard";
  const errorCode = searchParams.get("error");
  const errorMessage = errorCode ? (SIGN_IN_ERRORS[errorCode] ?? SIGN_IN_ERRORS.default) : null;

  async function handleSignIn() {
    setRedirecting(true);
    try {
      await signIn("keycloak", { callbackUrl });
    } catch {
      setRedirecting(false);
    }
  }

  return (
    <div className="space-y-4">
      {errorMessage ? (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-foreground"
        >
          {errorMessage}
        </p>
      ) : null}

      <Button
        variant="accent"
        size="lg"
        className="w-full"
        onClick={handleSignIn}
        disabled={redirecting}
      >
        {redirecting ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <LogIn className="mr-2 h-4 w-4" aria-hidden />
        )}
        {redirecting ? "Taking you to sign-in…" : "Sign in with Microsoft"}
      </Button>
    </div>
  );
}

export default function SignInPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="flex flex-col justify-between gap-10 bg-primary px-8 py-12 text-primary-foreground lg:px-14">
        <BrandMark variant="full" />

        <div className="max-w-md space-y-4">
          <h2 className="text-xl font-semibold">One place for a transaction’s paper trail</h2>
          <p className="text-sm leading-7 text-primary-foreground/80">
            AGFZE Command Centre is an internal AGFZE system that brings trade correspondence,
            documents, and approvals together, so everyone handling a transaction works from the same
            picture. It is being built to read incoming email and attachments and propose structured
            records - proposals only, which a named user verifies before anything is approved.
            Access is restricted to AGFZE staff and is governed by the role assigned to your account.
          </p>
        </div>

        <nav aria-label="Legal documents" className="flex flex-wrap gap-5">
          {LEGAL_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-primary-foreground/70 underline-offset-4 hover:text-primary-foreground hover:underline"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </section>

      <section className="flex items-center justify-center px-6 py-12 lg:px-14">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="text-2xl">Sign in</CardTitle>
            <CardDescription>
              Authentication is brokered by Keycloak. In production, Keycloak federates to Microsoft
              Entra ID, so you sign in with the Microsoft 365 credentials you already use; in other
              environments you sign in against the Keycloak realm directly.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Suspense fallback={<Skeleton className="h-11 w-full" />}>
              <SignInForm />
            </Suspense>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
