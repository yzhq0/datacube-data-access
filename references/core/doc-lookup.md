# Document Lookup

Read this file when the API name or `doc_id` is not already confirmed.

## Entry points

- Root index: `https://datacube.foundersc.com/document/2`
- Specific page pattern: `https://datacube.foundersc.com/document/2?doc_id=<doc_id>`

## Terminal-first lookup

Prefer the bundled entry point:

```bash
python scripts/search_datacube_docs.py "A股日行情"
python scripts/search_datacube_docs.py --doc-id 10303 --pattern "接口|输入参数|输出参数"
```

Renderer behavior:

- Windows or Windows-like shells: prefer the bundled Python renderer
- Unix-like shells: prefer `w3m`, then `lynx`, then Python
- Set `DATACUBE_DOC_RENDERER=python`, `w3m`, or `lynx` to override auto selection

If you are already on Unix and want the old wrapper form:

```bash
scripts/search_datacube_docs.sh "A股日行情"
```

## Browser-based lookup

Use `$playwright` when the site is easier to inspect in a real browser, for example:

- menu drilling is faster visually than via plain-text dumps
- the page updates dynamically
- repeated navigation and backtracking matter

## Lookup discipline

- Search by business concept first, then confirm the specific `doc_id`
- Do not infer an API contract from a similar page
- When accuracy matters, dump the actual page you intend to use and inspect the contract sections directly
