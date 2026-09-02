# syntax=docker/dockerfile:1
FROM golang:1.25-alpine3.22 AS builder

ARG EDGEX_GO_COMMIT=2526184332b489189495cbaa1266ec9db759a3df
ARG EDGEX_VERSION=4.0.2

RUN apk add --update --no-cache git make
RUN git init /edgex-go \
    && git -C /edgex-go remote add origin https://github.com/edgexfoundry/edgex-go.git \
    && git -C /edgex-go fetch --depth=1 origin "${EDGEX_GO_COMMIT}" \
    && git -C /edgex-go checkout --detach FETCH_HEAD

COPY patches/0001-core-data-device-query-pool-deadlock.patch /tmp/core-data.patch
RUN git -C /edgex-go apply --check /tmp/core-data.patch \
    && git -C /edgex-go apply /tmp/core-data.patch

WORKDIR /edgex-go
RUN go test ./internal/pkg/infrastructure/postgres -count=1
RUN VERSION="${EDGEX_VERSION}" make -e cmd/core-data/core-data

FROM alpine:3.22

LABEL org.opencontainers.image.title="EdgeX Core Data with device query fix" \
      org.opencontainers.image.source="https://github.com/edgexfoundry/edgex-go" \
      org.opencontainers.image.revision="2526184332b489189495cbaa1266ec9db759a3df" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV APP_PORT=59880
EXPOSE 59880

RUN apk add --update --no-cache dumb-init \
    && apk --no-cache upgrade

COPY --from=builder /edgex-go/Attribution.txt /
COPY --from=builder /edgex-go/security.txt /
COPY --from=builder /edgex-go/cmd/core-data/core-data /
COPY --from=builder /edgex-go/cmd/core-data/res/configuration.yaml /res/configuration.yaml

ENTRYPOINT ["/core-data"]
CMD ["-cp=keeper.http://edgex-core-keeper:59890", "--registry"]
