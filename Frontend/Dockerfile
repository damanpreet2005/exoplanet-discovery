FROM node:20-slim AS build

WORKDIR /srv

COPY package.json package-lock.json* ./
RUN npm ci

COPY index.html vite.config.js ./
COPY src ./src

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /srv/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5500
