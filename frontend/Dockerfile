FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Моки в продакшен-сборке выключены; включить можно только явно: --build-arg VITE_USE_MOCKS=1
ARG VITE_USE_MOCKS=0
ENV VITE_USE_MOCKS=$VITE_USE_MOCKS
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
