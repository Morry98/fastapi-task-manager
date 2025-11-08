# Usage notes
> [!IMPORTANT]  
> This needs to be moved inside the doc

local docs development:
```
uv run mkdocs serve
```
new version creation:
```
uv build
uv release
```
publish docs to github pages:
```
uv run mkdocs gh-deploy
```
