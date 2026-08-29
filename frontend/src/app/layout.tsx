import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import type { ReactNode } from "react";

import { Providers } from "@/components/providers";
import { ServiceWorkerRegistrar } from "@/components/pwa/service-worker-registrar";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

/**
 * Every page is rendered per request, and the reason is the Content-Security-Policy.
 *
 * The middleware mints a nonce per request and Next.js stamps it onto its own bootstrap scripts -
 * but only on a page it actually renders. A statically prerendered page's HTML was produced at
 * build time and cannot carry a per-request nonce, so under a nonce-based policy its scripts are
 * blocked and the page arrives dead. The sign-in page was exactly that: static, and the first
 * thing anybody sees.
 *
 * Declared once, in the root layout, rather than on the six pages that happened to prerender
 * today. A page added later cannot quietly become static and lose its scripts.
 *
 * The cost is negligible here: every page behind authentication was already dynamic, and the
 * public ones are a few hundred bytes of markup with no data behind them. The offline route is
 * unaffected - the service worker fetches and stores its response at install time, and what it
 * stores is a response either way.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: {
    default: "AGFZE Command Centre",
    template: "%s · AGFZE Command Centre",
  },
  description:
    "Internal operations platform for AGFZE trade correspondence, documents, approvals and logistics.",
  applicationName: "AGFZE Command Centre",
  // Internal platform: it must never be indexed and no crawler should follow links into it.
  robots: { index: false, follow: false },
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    // iOS reads this and nothing else for a home-screen install, and it never composites
    // transparency - which is why that icon is drawn opaque.
    apple: [{ url: "/icons/apple-touch-icon-180.png", sizes: "180x180", type: "image/png" }],
  },
  appleWebApp: {
    capable: true,
    // What iOS writes under the home-screen icon, which truncates past a dozen characters -
    // so it is the wordmark, exactly as the compact brand mark shows it.
    title: "AGFZE",
    // Ink navy behind the status bar, matching the header the app opens onto.
    statusBarStyle: "black-translucent",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // The ink navy of the design system, and the same value the web app manifest declares.
  themeColor: "#182338",
  // An installed app draws into the safe area on a notched device rather than letterboxing.
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={inter.variable}>
      <body className="min-h-screen bg-background font-sans text-foreground">
        <Providers>
          {/* Production builds only, and it unregisters itself under `npm run dev`. */}
          <ServiceWorkerRegistrar />
          {children}
        </Providers>
      </body>
    </html>
  );
}
