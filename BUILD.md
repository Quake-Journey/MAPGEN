# Building MAPGEN from source

## The generator (`pipeline.exe`)

MinGW-w64 GCC (C17) and zlib. From the repository's root:

```
python -c "import sys; sys.path.insert(0, 'tools'); from pathlib import Path; from check_mapgen_pipeline import build; print(build(Path('build')))"
```

`tools/check_mapgen_pipeline.py` lists the sources (`SOURCES`) and the flags.

## The map compiler (`q2tool.exe`)

The generator compiles maps with a pinned, patched build of q2tools-220 (GPL-2.0): `tools/build_pinned_compiler.py`
with the patches `tools/mapgen_patch_*.py`; `tools/mapgen_pinned_compiler.py` names the qualified build.

## MAPGEN Studio

.NET 10 SDK:

```
dotnet publish tools/mapgen_studio/MapgenStudio/MapgenStudio.csproj -c Release -r win-x64 --self-contained true -o out
```

Put `engine/pipeline.exe` and `engine/q2tool.exe` beside `MapgenStudio.exe`, and the `tools/` scripts the map checks
use in `tools/` beside it.

## The guide

`tools/check_mapgen_studio_guide.py --shots` retakes the screenshots from the current build;
`tools/mapgen_studio_guide_docx.py` and `tools/mapgen_studio_guide_html.py` make the DOCX and HTML.
