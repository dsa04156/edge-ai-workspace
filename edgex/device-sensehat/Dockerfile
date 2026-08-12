# syntax=docker/dockerfile:1.7
FROM golang:1.25.0-bookworm AS build

WORKDIR /src
COPY local-data-cache ./local-data-cache
COPY device-sensehat/go.mod device-sensehat/go.sum ./device-sensehat/
WORKDIR /src/device-sensehat
RUN go mod download
COPY device-sensehat ./
RUN CGO_ENABLED=0 GOOS=linux go build \
    -trimpath -ldflags="-s -w" \
    -o /out/device-sensehat ./cmd/device-sensehat

FROM 192.168.0.56:5000/edgex-device-sensehat-base@sha256:aaddfeadce5777fd57a0ef67c2adff10e72fd444d8c41dd9c344f706c5d7ceef
COPY --from=build /out/device-sensehat /usr/local/bin/device-sensehat

ENTRYPOINT ["/usr/local/bin/device-sensehat"]
