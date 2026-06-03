# Fix Notes

## Fixed: ELA forensic folder error

Previous error:

```text
[Errno 2] No such file or directory: ...\data\processed\<claim_id>\forensic\ela_page_1.recompressed.jpg
```

Cause: `forensic_service.py` tried to save a temporary recompressed ELA image before creating the `forensic` output folder.

Fix:

- Create `out_path.parent` before saving the recompressed image.
- Make ELA per-page failures non-fatal so the full claim pipeline can continue.
- Save a minimal failure analysis if any future processing error occurs, so the UI does not remain empty.

After replacing the project files, restart Uvicorn and upload the PDF again.
