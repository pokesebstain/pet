# 阶段 1：构建
FROM node:20-alpine AS builder
WORKDIR /app
COPY admin/package*.json ./
RUN npm ci
COPY admin/ ./
RUN npm run build

# 阶段 2：运行时
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80