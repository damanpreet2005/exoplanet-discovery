FROM node:20-slim

WORKDIR /srv

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY src ./src

EXPOSE 8000
CMD ["node", "src/server.js"]
