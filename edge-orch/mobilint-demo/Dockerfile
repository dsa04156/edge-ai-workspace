FROM python:3.11-slim-bookworm
WORKDIR /app
COPY libqbruntime.so.1.4.0 /usr/local/lib/
RUN ln -s libqbruntime.so.1.4.0 /usr/local/lib/libqbruntime.so.1 && ldconfig
COPY mobilint_qb_runtime-1.4.0-cp311-cp311-manylinux_2_31_x86_64.whl /tmp/
RUN pip install --no-cache-dir numpy==1.26.4 /tmp/mobilint_qb_runtime-1.4.0-cp311-cp311-manylinux_2_31_x86_64.whl && rm /tmp/*.whl
COPY style_candy.mxq style_mosaic.mxq /models/
COPY app.py /app/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python3", "/app/app.py"]
