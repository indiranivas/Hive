# Multi-stage: build the Next.js standalone bundle, then run it on a slim image.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
RUN addgroup -g 10003 hive && adduser -u 10003 -G hive -D hive
COPY --from=builder /app/public ./public
COPY --from=builder --chown=hive:hive /app/.next/standalone ./
COPY --from=builder --chown=hive:hive /app/.next/static ./.next/static
USER hive
EXPOSE 3000
CMD ["node", "server.js"]
