FROM node:26-alpine@sha256:ef24c5053d50fdc3e4e56eb4e7ddb7861874ab0fdc797046ba897581deb8e868 AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/package.json
RUN npm ci --no-audit --no-fund
COPY frontend ./frontend
ARG VITE_API_URL=/api/v1
ARG VITE_DEMO_MODE=false
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_DEMO_MODE=$VITE_DEMO_MODE
RUN npm run build

FROM nginx:1.31.6-alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2 AS runtime
ARG S3_PUBLIC_ENDPOINT_URL="http://localhost:9010"
ARG WEB_CSP_EXTRA_CONNECT_SRC="http://localhost:9010 http://127.0.0.1:9010"
COPY frontend/nginx.conf /tmp/northstar-nginx.conf.template
COPY frontend/render-nginx-config.sh /usr/local/bin/render-northstar-nginx
COPY frontend/render-nginx-config.test.sh /usr/local/bin/test-northstar-nginx-renderer
RUN apk upgrade --no-cache \
    && chmod 0555 /usr/local/bin/render-northstar-nginx /usr/local/bin/test-northstar-nginx-renderer \
    && /usr/local/bin/test-northstar-nginx-renderer /usr/local/bin/render-northstar-nginx /tmp/northstar-nginx.conf.template \
    && /usr/local/bin/render-northstar-nginx /tmp/northstar-nginx.conf.template /etc/nginx/conf.d/default.conf \
    && rm -f /tmp/northstar-nginx.conf.template /usr/local/bin/render-northstar-nginx /usr/local/bin/test-northstar-nginx-renderer
COPY --from=build /app/frontend/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
