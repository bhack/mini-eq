FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/src/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gir1.2-wp-0.4 \
        python3 \
        python3-gi \
        wireplumber \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY src/mini_eq ./src/mini_eq
COPY tools/check_wireplumber_gi.py ./tools/check_wireplumber_gi.py

CMD ["python3", "tools/check_wireplumber_gi.py", "--expect-version", "0.4"]
