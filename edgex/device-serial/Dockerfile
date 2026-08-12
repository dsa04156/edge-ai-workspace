# syntax=docker/dockerfile:1.7
FROM golang:1.25.0-bookworm AS build

WORKDIR /src
COPY local-data-cache ./local-data-cache
COPY device-serial/go.mod device-serial/go.sum ./device-serial/
WORKDIR /src/device-serial
RUN go mod download
COPY device-serial ./
RUN CGO_ENABLED=0 GOOS=linux go build \
    -trimpath -ldflags="-s -w" \
    -o /out/device-serial ./cmd/device-serial

FROM gcr.io/distroless/static-debian12:nonroot@sha256:f5b485ea962d9bd1186b2f6b3a061191539b905b82ec395de78cbfae51f20e35
COPY --from=build /out/device-serial /usr/local/bin/device-serial

ENTRYPOINT ["/usr/local/bin/device-serial"]
