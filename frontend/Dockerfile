# Multi-stage: build con node, servir estáticos con nginx (que también hace
# de proxy hacia el servicio `api` -- así tampoco hace falta CORS en producción).

FROM node:22-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
