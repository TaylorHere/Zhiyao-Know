Offline tiktoken cache source files

Put tokenizer source files in this directory before building `api` image.
During Docker build, files will be copied into `TIKTOKEN_CACHE_DIR` using
the hashed cache keys that `tiktoken` expects.

Supported filenames:

- `o200k_base.tiktoken`
- `cl100k_base.tiktoken`
- `p50k_base.tiktoken`
- `r50k_base.tiktoken`
- `gpt2_vocab.bpe`
- `gpt2_encoder.json`

Current repository includes:

- `o200k_base.tiktoken`

If a file is missing, build will continue and print it in
`missing_optional_tiktoken_files`.
