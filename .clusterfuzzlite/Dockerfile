FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9
COPY --from=uv /uv /usr/local/bin/uv
COPY . $SRC/cat-care
WORKDIR $SRC/cat-care
ENV UV_PYTHON_INSTALL_DIR=/opt/python FUZZ_VENV=/opt/fuzz
RUN uv venv --managed-python --python "$(cat .python-version)" "$FUZZ_VENV" \
 && uv pip install --python "$FUZZ_VENV/bin/python" --require-hashes -r .clusterfuzzlite/requirements.txt
COPY .clusterfuzzlite/build.sh $SRC/
