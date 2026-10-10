# Results page

The probe results page (published as a claude.ai artifact) is built from `exports/`:

```sh
uv run python analysis/export.py
uv run python analysis/results_page/build_data.py exports /tmp/data.json
python3 -c "import pathlib as p; t=p.Path('analysis/results_page/template.html').read_text(); \
d=p.Path('/tmp/data.json').read_text().replace('</','<\\\\/'); p.Path('probe-results.html').write_text(t.replace('__DATA__', d))"
```
