# Frontend for Docker Compose: the Vite dev server on port 5173. It proxies
# /api to API_PROXY_TARGET (set by Compose). The source is copied in: no bind
# mount, no hot reload.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
