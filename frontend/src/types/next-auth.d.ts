import type { DefaultSession } from "next-auth";

import type { PlatformRole } from "@/lib/roles";

declare module "next-auth" {
  interface Session {
    user: DefaultSession["user"] & {
      id: string;
      roles: PlatformRole[];
    };
    accessToken?: string;
    idToken?: string;
    expiresAt?: number;
    error?: "RefreshAccessTokenError";
  }

  interface User {
    roles?: PlatformRole[];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    idToken?: string;
    expiresAt?: number;
    roles?: PlatformRole[];
    error?: "RefreshAccessTokenError";
  }
}
