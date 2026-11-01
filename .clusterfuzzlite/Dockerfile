FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9
COPY --from=uv /uv /usr/local/bin/uv
COPY . $SRC/cat-care
WORKDIR $SRC/cat-care
ENV UV_PYTHON_INSTALL_DIR=/opt/python FUZZ_VENV=/opt/fuzz
RUN uv venv --managed-python --python "$(cat .python-version)" "$FUZZ_VENV" \
 && uv pip install --python "$FUZZ_VENV/bin/python" --require-hashes -r .clusterfuzzlite/requirements.txt
COPY .clusterfuzzlite/build.sh $SRC/
