# Use the matching, digest-pinned Python base listed in ../examples/digits-model/README.md.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY server.py model.json /opt/demo/
USER 65532:65532
ENTRYPOINT ["python", "/opt/demo/server.py"]
