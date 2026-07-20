# Next.js front end — build for production, then serve with `next start`.
# NEXT_PUBLIC_API_URL is inlined at BUILD time (it runs in the browser), so it is
# passed as a build arg; it must be the URL the browser reaches the API at.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:5050
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000
CMD ["npm", "run", "start"]
