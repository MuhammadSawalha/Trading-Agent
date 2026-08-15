FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Processed as a template (envsubst, via the base image's own docker-entrypoint.d scripts) so
# ${NGINX_LOCAL_RESOLVERS} below gets filled in with the DNS resolver from /etc/resolv.conf.
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
# Overridden per-namespace by the Helm chart under Kubernetes; this default is the
# docker-compose service name, unqualified, which resolves fine there as-is.
ENV API_BACKEND_HOST=api-backend
EXPOSE 80
