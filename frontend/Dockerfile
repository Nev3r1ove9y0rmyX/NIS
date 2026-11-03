# 构建阶段：Node 20 + 国内 npm 镜像
FROM node:20-alpine AS build
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
WORKDIR /app
RUN npm config set registry https://registry.npmmirror.com
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# 运行阶段：nginx 托管静态资源
FROM nginx:1.27-alpine AS runtime
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/nis-frontend.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
