# Use the already-published local docs image as the base so docs-only rebuilds
# do not depend on Docker Hub pulling nginx:1.27-alpine.
# Bootstrap note: if the local registry is empty, build once with nginx:1.27-alpine
# and push 192.168.0.56:5000/docs-html:latest first.
FROM 192.168.0.56:5000/docs-html:latest
COPY docs/html/ /usr/share/nginx/html/
COPY docs/assets/ /usr/share/nginx/html/assets/
