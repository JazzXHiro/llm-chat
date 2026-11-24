# ---------- Stage 1: build the React app with Node ----------
FROM node:24-alpine AS build

WORKDIR /app

# Install exact versions from package-lock.json (layer cached until it changes)
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite bakes VITE_* variables into the JS at BUILD time, so the backend URL
# is a build argument, not a runtime env variable.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build


# ---------- Stage 2: serve the static files with nginx ----------
FROM nginx:stable-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
