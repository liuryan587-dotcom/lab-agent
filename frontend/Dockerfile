# 前端镜像：多阶段构建，最终只留静态文件 + nginx
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# 注意：不要在生产构建里注入 VITE_API_BASE_URL，
# 留空才能让请求走同源 /api，由 nginx 反代到后端
RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
