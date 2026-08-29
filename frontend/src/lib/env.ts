import { z } from "zod";

const issuerUrl = z
  .string()
  .url()
  .transform((value) => value.replace(/\/+$/, ""));

const serverSchema = z
  .object({
    KEYCLOAK_CLIENT_ID: z.string().min(1),
    KEYCLOAK_CLIENT_SECRET: z.string().min(1),
    KEYCLOAK_ISSUER: issuerUrl,
    KEYCLOAK_INTERNAL_ISSUER: issuerUrl.optional(),
    NEXTAUTH_URL: z.string().url(),
    NEXTAUTH_SECRET: z.string().min(1),
    // Same browser-vs-container split as the issuer: server-side rendering reaches the API on the
    // compose network, the browser reaches it on the published port.
    API_INTERNAL_BASE_URL: z.string().url().optional(),
    NEXT_PUBLIC_API_BASE_URL: z.string().url(),
    // The VAPID application server key. Public by the Web Push standard's own design - the
    // browser is handed it to bind a subscription with - and optional, because a deployment that
    // has generated no key pair simply has no push and says so. The PRIVATE half is a backend
    // secret and has no representation anywhere in this file.
    NEXT_PUBLIC_VAPID_PUBLIC_KEY: z.string().optional(),
  })
  .transform((env) => ({
    ...env,
    KEYCLOAK_INTERNAL_ISSUER: env.KEYCLOAK_INTERNAL_ISSUER ?? env.KEYCLOAK_ISSUER,
    API_INTERNAL_BASE_URL: env.API_INTERNAL_BASE_URL ?? env.NEXT_PUBLIC_API_BASE_URL,
  }));

const clientSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z.string().url(),
  NEXT_PUBLIC_VAPID_PUBLIC_KEY: z.string().optional(),
});

export type ServerEnv = z.infer<typeof serverSchema>;
export type ClientEnv = z.infer<typeof clientSchema>;

// Names and reasons only - the values are secrets and must never reach a log or a stack trace.
function environmentError(scope: string, error: z.ZodError): Error {
  const problems = error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"} - ${issue.message}`)
    .join("; ");
  return new Error(
    `${scope} environment is not configured: ${problems}. ` +
    "Set these variables before starting the app (see frontend/.env.example).",
  );
}

let serverCache: ServerEnv | null = null;
let clientCache: ClientEnv | null = null;

export function getServerEnv(): ServerEnv {
  if (!serverCache) {
    const result = serverSchema.safeParse({
      KEYCLOAK_CLIENT_ID: process.env.KEYCLOAK_CLIENT_ID,
      KEYCLOAK_CLIENT_SECRET: process.env.KEYCLOAK_CLIENT_SECRET,
      KEYCLOAK_ISSUER: process.env.KEYCLOAK_ISSUER,
      KEYCLOAK_INTERNAL_ISSUER: process.env.KEYCLOAK_INTERNAL_ISSUER || undefined,
      NEXTAUTH_URL: process.env.NEXTAUTH_URL,
      NEXTAUTH_SECRET: process.env.NEXTAUTH_SECRET,
      API_INTERNAL_BASE_URL: process.env.API_INTERNAL_BASE_URL || undefined,
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
      NEXT_PUBLIC_VAPID_PUBLIC_KEY: process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || undefined,
    });
    if (!result.success) throw environmentError("Server", result.error);
    serverCache = result.data;
  }
  return serverCache;
}

export function getClientEnv(): ClientEnv {
  if (!clientCache) {
    // Next.js only inlines NEXT_PUBLIC_* for property accesses written out in full, so this one
    // cannot be read through a computed key.
    const result = clientSchema.safeParse({
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
      NEXT_PUBLIC_VAPID_PUBLIC_KEY: process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || undefined,
    });
    if (!result.success) throw environmentError("Client", result.error);
    clientCache = result.data;
  }
  return clientCache;
}
