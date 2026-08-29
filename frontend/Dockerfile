FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
# NEXT_PUBLIC_* values are baked into the client bundle, so this one has to be present at build
# time; the runtime environment cannot supply it afterwards.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
# The VAPID application server key, public half. The browser is handed it to subscribe with, so
# it too has to be present at build time. The private half is a backend secret and never appears
# in this image. Left empty, the app simply has no push and says so.
ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY=
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_VAPID_PUBLIC_KEY=$NEXT_PUBLIC_VAPID_PUBLIC_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# `npm run build` also runs the postbuild step that writes public/sw.js - the service worker is
# produced by a production build and by nothing else, which is the same rule that keeps it out of
# `npm run dev`.
RUN mkdir -p public && npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
