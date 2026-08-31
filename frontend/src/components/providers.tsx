"use client";

import type { Session } from "next-auth";
import { SessionProvider } from "next-auth/react";
import type { ReactNode } from "react";
import { Toaster } from "react-hot-toast";

export interface ProvidersProps {
  children: ReactNode;
  session?: Session | null;
}

export function Providers({ children, session }: ProvidersProps) {
  return (
    <SessionProvider session={session}>
      {children}
      {/* Toasts sit on the top layer of the CCDS stacking scale - above modals and popovers,
          because a confirmation that a dialog covered is a confirmation nobody got. */}
      <Toaster
        position="top-right"
        containerStyle={{ zIndex: 700 }}
        toastOptions={{
          duration: 5000,
          style: {
            background: "hsl(var(--elevation-surface-overlay))",
            color: "hsl(var(--color-text-default))",
            border: "1px solid hsl(var(--color-border-default))",
            borderRadius: "var(--radius)",
            fontSize: "14px",
            lineHeight: "20px",
            boxShadow: "var(--shadow-raised)",
          },
          success: {
            iconTheme: {
              primary: "hsl(var(--color-background-success-bold))",
              secondary: "hsl(var(--color-text-inverse))",
            },
          },
          error: {
            iconTheme: {
              primary: "hsl(var(--color-background-danger-bold))",
              secondary: "hsl(var(--color-text-inverse))",
            },
          },
        }}
      />
    </SessionProvider>
  );
}
