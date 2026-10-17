#!/bin/bash -eu
export PATH="$FUZZ_VENV/bin:$PATH"
uv pip install --python "$FUZZ_VENV/bin/python" --no-deps .

for fuzzer in "$SRC"/cat-care/fuzz/*_fuzzer.py; do
  fuzzer_basename=$(basename -s .py "$fuzzer")
  fuzzer_package=${fuzzer_basename}.pkg
  pyinstaller --distpath "$OUT" --onefile --name "$fuzzer_package" \
    --add-data "$SRC/cat-care/skrypka_bot/prompts:skrypka_bot/prompts" "$fuzzer"
  cat > "$OUT/$fuzzer_basename" <<WRAPPER
#!/bin/sh
# LLVMFuzzerTestOneInput for fuzzer detection.
this_dir=\$(dirname "\$0")
ASAN_OPTIONS=\$ASAN_OPTIONS:symbolize=1:external_symbolizer_path=\$this_dir/llvm-symbolizer:detect_leaks=0 \
\$this_dir/$fuzzer_package "\$@"
WRAPPER
  chmod +x "$OUT/$fuzzer_basename"
done
