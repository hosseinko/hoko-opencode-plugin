# The test suite only: bun for plugin/test_hoko.ts, python3 for the journal scripts.
# The plugin itself needs neither — it uses node's standard library only.
FROM oven/bun:1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 git make \
    && rm -rf /var/lib/apt/lists/*

# The suite imports solid-js. Installing at the image root keeps node_modules out of the
# bind-mounted working tree, which would otherwise hide it at /work.
COPY package.json bun.lock /
RUN cd / && bun install --frozen-lockfile

WORKDIR /work
