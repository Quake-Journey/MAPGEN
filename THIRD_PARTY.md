# Third-party parts

- **Q2PRO** (GPL-2.0) — the engine files the generator is built with (`inc/shared`, `src/shared`, `src/common/pmove`,
  `inc/common/pmove.h`): player movement for the reachability walk, shared definitions.
- **q2tools-220** (GPL-2.0) — the map compiler the generator runs; this repository holds the patches applied to it
  (`tools/mapgen_patch_*.py`) and the build script.
- **Avalonia**, **FluentAvalonia**, **.NET** — the Studio's UI framework and runtime (MIT).
- **Procedural-PBR** by Whappens (MIT, https://github.com/Whappens/Procedural-PBR, commit 30c7111) — its seamless
  noise (Perlin, fBm, Voronoi, toroidal blur) and its brick recipe, adapted in `tools/mapgen_texgen_noise.py` and
  `tools/mapgen_texgen.py` (the Studio's own textures); its licence in `tools/third_party/procedural_pbr_LICENSE.txt`.
- No map is distributed. Quake II and its maps are id Software's.
