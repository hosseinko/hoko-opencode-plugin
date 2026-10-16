# The test suite only: bun for plugin/test_hoko.ts, python3 for the journal scripts.
# The plugin itself needs neither — it uses node's standard library only.
FROM oven/bun:1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
