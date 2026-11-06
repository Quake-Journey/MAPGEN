# MAPGEN by ly

**MAPGEN** makes new Quake II maps two ways. **From scratch**: set the players and the mode, the size, the levels, the
layout (two halves, one arena, a ring, an open space of islands in the void, a tower of storeys round an atrium), the
ways, weapons, items and the mechanics of people's maps — or pick one of 184 presets — and it lays the map out, dresses
it as people's maps are dressed (or in the Studio's own textures) and checks it against people's maps. **From an
existing map**: it digs passages through the rock, carries rooms over from another map, floods low ground, changes the
finish, moves items. Either way it checks that the new map can be walked, is lit and has nothing broken. **MAPGEN
Studio** is its Windows program.

- Download: the latest build is in [Releases](https://github.com/Quake-Journey/MAPGEN/releases) — unpack the zip and
  start `MapgenStudio.exe`. You need Quake II (any client with its `baseq2`); Python 3.10+ for the map checks (the
  Studio offers to install it). No maps are shipped: a map from scratch needs none; any Quake II `.bsp` of your game
  can be a base.
- Guide: [English](doc/mapgen_studio/MAPGEN_Studio_Guide_EN.md) · [Русский](doc/mapgen_studio/MAPGEN_Studio_Guide_RU.md)
- Changes: [CHANGELOG.en.md](CHANGELOG.en.md) · [CHANGELOG.ru.md](CHANGELOG.ru.md)
- Building from source: [BUILD.md](BUILD.md)

---

**MAPGEN** делает новые карты Quake II двумя путями. **С нуля**: задайте, на сколько игроков и в каком режиме,
размер, уровни, устройство (две половины, одна арена, кольцо, открытый космос из островов в пустоте, башня из этажей
вокруг атриума), переходы, оружие, предметы и механики с карт людей — или возьмите один из 184 пресетов, — и генератор
сам построит планировку, оденет карту, как одеты карты людей (или в свои текстуры студии), и проверит её мерками карт
людей. **Из готовой карты**: прокладывает проходы в скале, переносит комнаты из другой карты, заливает низины, меняет
отделку, переставляет предметы. В обоих случаях проверяет, что по новой карте можно пройти, что она освещена и в ней
ничего не сломано. **MAPGEN Studio** — программа для Windows.

- Скачать: свежая сборка в [Releases](https://github.com/Quake-Journey/MAPGEN/releases) — распакуйте архив и
  запустите `MapgenStudio.exe`. Нужен Quake II (любой клиент с папкой `baseq2`) и Python 3.10+ для проверок карт
  (студия сама предложит его установить). Карты не входят в сборку: карте с нуля они не нужны, основой можно взять
  любую карту `.bsp` вашей игры.
- Руководство: [Русский](doc/mapgen_studio/MAPGEN_Studio_Guide_RU.md) · [English](doc/mapgen_studio/MAPGEN_Studio_Guide_EN.md)
- Изменения: [CHANGELOG.ru.md](CHANGELOG.ru.md) · [CHANGELOG.en.md](CHANGELOG.en.md)

This repository is published one way from the authors' working tree; changes made here directly are not taken back.
