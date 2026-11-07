# MAPGEN Studio by ly — user guide

MAPGEN Studio makes new Quake II maps in two ways.

- **From an existing map** — it remakes it: digs passages through the rock, carries rooms over from another map,
  floods low ground with water, lava or slime, changes the finish, moves items. The base map stays as it is; the new
  map is put beside it.
- **From scratch** — it builds a new map by the parameters: how many players it is for, how many levels, lifts, jump
  pads and how much water it has, which weapons, which ways of play and in which style. See «A new map from scratch»
  below.

Either way the Studio checks that the new map can be walked, that it is lit and that nothing in it is broken.

Every screenshot in this guide was taken by the program itself, from the version the guide ships with.

## What you need

- Windows 10 or 11, 64-bit.
- Quake II with its `baseq2` folder — any client: the textures come from it, and the game is started from it for
  the covers.
- Python 3.10 or newer — for the checks of a finished map. When there is none, the program offers to install it
  itself («Install Python» downloads the official installer from python.org and installs it for you only, no
  administrator needed) or to be pointed at one already installed («Point to Python…»). Without Python the map is
  still built, but the checks are skipped.
- Base maps: the program ships no maps. Any Quake II map file (`.bsp`) from your game can be added as a base from
  inside the program.

## First start

While the Studio is loading, a loading window shows how much is done and what is being done now (the window look,
reading the map library, the newest map's cover, finding Python and the game, loading the Studio). The share is
weighed by how long each step took at the last start, so on a slow computer or disk the bar moves as that machine
loads. The first start after installing takes longer than usual.

![Home](screens/en/home.png)

On the left is the menu: **Home**, **Generate**, **Maps**, and at the bottom **Settings** and **About**. Each section
has its coloured sign; the one under the mouse lights up, the open one stands out in its colour with a bar on the
left. The ☰ button at the top folds the menu to its signs and opens it again.

On the home page:

- **Two paragraphs on the Studio and its generator** — what they do and why what comes out is always playable.
- **The community's links** under them: **News** (the Telegram channel, https://t.me/Q2RTX), **Community group**
  (the Telegram group, https://t.me/Q2PROX) and **Site** (http://q2pro-x.com/mapgen); they open in the browser.
- **Three large buttons**: «New map» — to the generation, «Maps» — to the library (the button says how many maps it
  holds), «Guide» — opens this guide.
- **The latest map** — the newest map in the library: its cover, base, checks and «Open the map». While a run goes
  on, what it is doing now and «Open the run» stand there instead.
- **Readiness** — whether everything is set: the game client (the game's folder that holds `baseq2`), the generator
  (the `engine` folder beside the program; without it the build is damaged), Python and the finished maps' checks.
  When something is missing, the button to fix it is right there: «Open settings», «Install Python», «Point to
  Python…».
- **Documentation** — the guide comes with the program (the `doc` folder beside it) and opens without the internet:
  in the browser, in Word, in Russian; «What is new» — the versions' history; the documentation folder.
- **How to make a map** — four steps.

**The run strip.** While a run goes on, a strip stands over every page but the run's own: the map's name and its
base, what is going on now and how long is left, the difference from the base, how many edits were accepted and how
many builds made, a bar and «Open the run» (a click on the strip does the same). Once the run is over, the strip
stays until you look at its page.

## Generate

![Generate](screens/en/generate.png)

The page is laid out in cards, in as many columns as the window's width holds: one on a narrow window, three on a
wide monitor; the cards are dealt so the columns end about even. At the top — **Base map**, **The new map** (likeness
to the base, the generation's time, the variant number, the name) and **The finished map** (keep its source, take
covers by itself). Under them the generation's options, cards by group: **The base's frame**, **New rooms**, **The
base rebuilt**, **Water, slime, lava**, **Ruin** and **What may change**. At the page's foot, wherever you are on the
page, the line «The map … will be made: base …, likeness …, up to … min» and the **«Start generating»** button.

**Presets.** Right of the page's title — the preset set now and the buttons **«Load»**, **«Create»**, **«Change»**,
**«Delete»**. A preset is a saved set of the page's parameters. «Load» opens a menu by category: the factory presets
(they cannot be changed or deleted) and your own. «Create» saves the parameters now under a name and a category of
your own. A map from a base and a new map from scratch have sets of their own.

### Base map

Tick one map or several. «Choose maps…» adds any Quake II map file from the disk — it is copied next to the program
and stays in the list. Each map says whether the generator has already been proven on it or this is a first trial.

With several maps ticked, choose what to make of them:

- **A map from each** — every ticked map becomes the base of its own new map, one after another.
- **One map from several** — the first ticked map is the base; from the others the generator takes rooms and carries
  them into the rock whole, with their walls, ceiling, lamps and ornaments.

### Likeness and variant

- **Likeness to the base, %** — how much the new map should stay like the old one. 90 is almost the same map with
  a few changes; 10 lets the generator change everything it can. Any number from 1 to 100.
- **Variant number** — the number that decides which changes are picked. The same base, likeness and number give the
  same map; another number, another map.
- **Map name** — Latin letters and digits. The program suggests one: `mg_` + likeness + variant number.

### The base's frame

Before building anything onto it, the generator may change the base itself:

- **Size** — the new map's area against the base's, 10 to 1000 %. A map made larger grows as tall, in proportion:
  halls become taller as well as wider. The steps and ledges that could no longer be climbed get gentle ramps or
  small flights in front of them; the gaps in gratings a player could not fall through are bridged; lifts and jump
  pads follow the new height. When full height leaves somewhere unwalkable, the generator tries a little less height
  until the whole map walks. A map made smaller keeps its height. Items and players' starts stay at their own
  height over the floor. The light of a large map is computed with a step chosen for its size — a map made several
  times larger does not come out dark.
- **Spread** — how unequally the base's parts stretch.
- **Shift** — how far the parts slide sideways against each other.
- **Turn** — the whole base turned or mirrored.
- **Ceiling height** — over the proportional height: everything above the highest place a player can stand is lifted
  further. 100 % — in proportion to the map's size. On a very large map the ceilings may run out of room — the
  game's coordinates are limited; they then rise as far as the game holds, and the run's log says so in a line like
  «The ceilings rose to 134 % of the 200 % asked: the game's coordinates hold no more».

### Scope of the changes

![The generation's options](screens/en/generate_options.png)

How much of what to build is set by the cards under the base: **New rooms** (passages, annexes, halls, bridges,
stairways), **The base rebuilt** (walls, blocks, the floor, stairs, ornaments), **Water, slime, lava** and **Ruin**.
Each option has a «Default» — then the generator decides by the likeness. Any other value is your direct order:

- **New passages** — how many new tunnels and stairs to dig through the rock between rooms.
- **Annex rooms with pickups** and **Annex size** — how many annex rooms with a weapon or armour to add, and how big
  (small, medium, large, halls).
- **Two-storey rooms** — how many rooms get a gallery and stairs to an upper level.
- **Bridges over the arena** — how many bridges to throw over open space.
- **Halls on long passages**.
- **Liquids** — turn the base's liquids into others: water to lava, lava to water, slime to lava and so on, or mix.
  Look and harm both change: lava burns, slime eats, water is swum in.
- **Wall decorations** — the generator finds the base's lamps and repeated ornaments on its walls and hangs the same
  in its tunnels: none, few, many, very many.
- **New water**, **New slime**, **New lava** — three sliders. By default the generator decides; 0 adds none of that
  liquid; 100 fills every room it can. The generator floods only rooms with a level floor and no room underneath,
  and never cuts off an item or a way. Lava and slime stay away from the player starts; passages between rooms are
  flooded with water only.
- **Stairway annexes** — from «None» to 10. The generator builds new platforms 96-192 high with stairs up to them:
  along rooms' walls and standing free on open floor (at most half of them). A pickup of that part of the map stands
  on each, or, by a wall, the platform leads onto a ledge of the map. It finds the places on any base by itself - a level floor, room around it and above it; when the map has
  fewer places than asked, there are fewer platforms, and the map's description says so.
- **Remodel the base** — how many times to change the base map itself rather than build onto it: a room's wall
  moved in, a wall turned at an angle, a terrace with steps raised along a wall.
- **Blocks in the rooms** — how many blocks to stand in the base's own rooms: a box, an L, a cross, an octagon or a
  round one, 64 to 192 across, turned at different angles. Low ones (32-64) to climb, high ones (96-128) a cover;
  against a wall or free, in the room's own material.
- **Floor: daises and channels** — how many times to change the base's own floor: raise a dais stepped on every
  side (a box or an octagon, 32-80 high) or sink a channel across the floor (32-64 deep) with a flight at both ends.
  A channel is dug only where no other room lies under the floor; the arena first.
- **Rebuild the base's stairs** — how many of the base's own stairs to rebuild in another shape between the same
  two floors: the old flight becomes a landing, reached by a half-round foot of steps or by a side flight. It needs
  open flat floor in front of the stair.

  For all four «Default» lets the generator decide by the likeness (the less alike, the more changes). When a map
  offers fewer places than asked, fewer are made, and the map's description says so.
- **Destruction** — a slider from 0 to 100 %. At 0 the map is made as usual, with every passage check. The higher,
  the more is destroyed: cracks in walls and floors, rubble, craters, breaches in walls, broken ledge edges, fallen
  ceilings, blocked corridors; at 100 almost the whole level. The player starts always stay free and no pickup is
  buried; passage, though, is not guaranteed. For the ruin the generator uses its own texture pack (earth, stone,
  concrete, brick, metal, gravel and more) matched to the map's own colours; the pack goes into the game's folder
  with the map.

The «What may change» card lists the families of changes; any can be switched off.

In the «The finished map» card: «Keep the map source (.map)» leaves the source beside the finished map, for a map
editor; «Shoot covers automatically» — after every finished map the program starts the game itself and takes a cover.

The generator cuts windows by itself, as many as the likeness allows: fixed glass, glass that drops when shot and
comes back after a while, and glass a pressure plate on the floor opens. Windows come in different outlines -
rectangular, round or oval, arched, with a transom and a vent - and with different glass: pale, blue, wired
lavender and grey, amber, olive, smoke.

«Start generating» starts the work. When the map's name is taken — the library has a map of that name, a past
generation's records are there, such a generation is running, queued or interrupted — the program asks first:
**Overwrite** (the new map replaces the old one with its records), **Correct the name** (the page scrolls to «Map name»,
the cursor in it) or **Cancel**. A running generation cannot be overwritten — only the name corrected or
the generation cancelled.

## A new map from scratch

![A new map from scratch: open space](screens/en/generate_scratch.png)

At the top of the Generate page the card **Where the map comes from** has two buttons: «From existing maps» (all that
is described above) and «A new map from scratch». From scratch the generator takes nobody's map: it lays out a
skeleton itself — rooms, levels, the ways between them, the places of weapons, armour and spawns — by the rules seen
on the maps people make, builds a real map from the skeleton, dresses it with its edits and checks it.

The easiest start is a preset: «Load» → a category (duels, free for all, big maps, team games, worlds, water and lava,
weapons, ways, mechanics, look, open space, tower — 184 factory presets in all) → a preset; then «Start generating».
Any parameter of a preset can be changed before the start.

The parameters are laid out in cards. Each list starts with «Default» — the value the generator chooses itself from
the player count; which one is said in brackets.

- **Who for** — how many players (2 — a duel, three to eight — free for all, more — a big map), the mode (duel, free
  for all, team against team — for teams the stack is repeated in both halves), how many spawns.
- **Size and shape** — the map's size (the floor area in percent of the usual for this player count), height levels,
  the vertical span, the share of corridors and open places, the sky overhead, long sight lines, the **layout** and
  **round shapes** (rounded corners, half-round hall ends, podiums — as on medusa_b1). The layouts:
  - **two halves** — each with a value of its own (the stack in one, the railgun in the other);
  - **one arena** — everything round a big hall;
  - **a ring** — rooms round a circle;
  - **open space** — islands hang in the void with no walls, jump pads, bridges and teleporters between them; a step
    off the edge is death;
  - **a tower** — whole storeys over each other round an atrium under the sky: up by jump pads and shafts, down by
    jumping, ledges over the top storey only a jump pad reaches.
- **Open space** and **A tower** — these layouts have a card of their own beside «Size and shape». Open space: how
  many islands, how many only a jump pad reaches, open or railed edges, the height spread, the pads' reach, bridges.
  A tower: how many storeys, the storey's height, how many shafts, how many ledges at the top. What they never have,
  the form does not show for them: an open space has no liquids, pits, round shapes, stairs, lifts, doors, windows or
  wall decorations — of the ways only teleporters; a tower has no liquids, pits, round shapes, stairs, lifts, doors
  or windows. When an older preset asks for them, the generator does not build them and says so in the description.
- **The new map** and **The finished map** — the generation's time, the variant number and the name; keep the source
  and take covers or not. **«Random variant»** (on by default) — each run takes a new number itself, and each time
  another map comes out; the number is in the map's name. To repeat a map, turn it off and enter the number: the same
  parameters and number give the same map.
- **Liquids** — the floor's shares under water, lava and slime, and deadly pits. Water lies only in hollows, each with
  steps up. «Let water stand above the floor» (off) lets rooms be flooded over the floor when more water is asked
  than the pits hold; without it the shortfall is said in the description.
- **Ways** — stairs, ramps, lifts, jump pads, teleporters, ladders, drops, doors and windows between rooms. Jump pads
  and teleporters look as on well-known maps: a lit disc on a plinth for a jump up, a slanted plate with arrows for a
  flight away, arrows running over it the way one flies; a teleporter stands in a frame of two posts with a
  shimmering portal.
- **Mechanics** — ways of play from well-known maps: a stack on the clock, two halves, a gun on a ledge, route
  asymmetry, many small health spots, spawn pressure, a dead-end stack, three approaches, a teleporter to the mirror
  stack, a jump pad over a pit, a lift as a weak spot, a ladder under an item. The check looks for each one turned on.
- **Weapons and items** — how many of each weapon, the armour and the stack (sets or your own), shards, ammo and
  health per player, the share of major items up high. **How hard the powerups are to get**: easy — on a pedestal
  under its own light; medium — in a nook in a wall, every other one raised (jump in); hard — in a nook behind a door
  a button on the wall opens; mixed. **«Armour and mega taking turns in one nook»** — the red armour and the mega
  appear by turns in one place, as on q2dm8.
- **Style** — **textures**: «Like people's maps» (the default: the generator takes one of q2dm, q2duel, ztn2dm,
  koldduel1, omf, ptrip, match1, kaktus and dresses the map in its wall, floor and ceiling textures, its trims, lamps
  and tinted light), «The chosen maps» (a button with every map of the game, a search and ticks; only their dressing
  is taken, none of their walls or rooms), «Mixed» or «Made by the Studio» — the Studio draws a texture set itself in
  the theme chosen (tech, gothic, factory, bunker, snow and ice, forest, city, another planet, fantasy, desert, hell),
  with its colour, wear, detail size and relief. Then wall decorations, the sun, the light's colour, **«Ships in the
  sky»** (up to three ships of the single-player game fly over the map) and the dressing edits — how far the generator
  changes the map built from the skeleton with its edits.
- **Ruin** — as for a map from a base.

![A new map from scratch: a tower](screens/en/generate_scratch_tower.png)

While the run goes, its first stage on its page is **The map's skeleton**: of many variants the best by the
measures of well-known maps is chosen, and its picture — the places, the levels (the lighter, the higher), the ways, weapons and items —
appears before the first wall. Over it all — **Progress**: the percent of the whole build, how long is left and when
it will end, which stage is on («Stage 5 of 11: Edits»).

A big map from scratch — an 8-player open space of a large area, say — stands in the middle of Quake II's world, not
in one half of it, so it is built however much room its islands take.

The finished map goes through the same checks as a map from a base, and two more:

- **From scratch** — it is measured as well-known maps are (size, levels, the ways' width, visibility, ways out of item
  places, light, the textures' colour and brightness, for an open space the islands and the pads' flights), and it has
  all its parameters and mechanics asked for. It has no place one can get into and not out of; lifts ride only through
  air; spawns stand away from teleporters and jump pads; water does not stand above a floor. It is checked as the
  library gets it — after the ruin and the light. The light it was built with stays to the end.
- **Not a copy** — it holds no rooms, pieces of route or item placings carried over from the maps the generator
  knows.

![A map from scratch in the library](screens/en/map_scratch.png)

A map from scratch's description starts with «Made from scratch: 4 players, free for all, dressed as people's map
q2dm1» and a table «Asked → made, on the finished map» for every parameter; then the mechanics, and everything that
did not come out named in words with its reason. Its tile and card say «from scratch» (and the style, when taken from
maps).

## A run

![A run](screens/en/run.png)

The page is in two parts: on the left what matters about the run, on the right the map's scheme the window's whole
height.

**At the top** — the map's name and the base it is made from. Under them a coloured badge with what is going on now
and its time: blue — running, yellow — paused, green — the map is ready, red — the run failed. Beside it, how long
the run has gone and when it began. The buttons are on the right.

**On the left**, always open:

- **Progress** (a map from scratch) — the percent of the whole build, how long is left and when it will end, which
  stage is on.
- **Difference from the base** (a map from a base) — large, how far the map already differs from the base in percent, of how many
  asked, and a bar. Under it, what the plan promises: how far it can change the map in the builds allowed.
- **Edits** — three numbers: how many edits were accepted (green), how many builds were made and how many edits were
  considered. Under them the run's time bar, and below the last edit: green when accepted, red when refused. After
  the edits the generator swaps liquids, moves items and tries rooms of other maps — that shows here too («N of M»).
- **The plan** — a table: what is planned by kind (new passages, annex rooms, two-storey rooms, bridges, pools,
  windows, stairway annexes, remodels of the base, rooms of the second map and others), with a bar and «done of
  planned». A kind done turns green. Destruction comes after the edits and the checks; its percent is named under
  the table.

**On the left**, folded (a click on the header opens and closes it):

- **Stages** — Getting ready → Building the base map → Making the plan of edits → Edits → Checking it is playable
  → Light and visibility → The map's checks → (Destruction - when asked for) → Light on the finished map → Cover →
  Done. The stage under way shows its time; a finished one, how long it took and when it ended. The stage now is
  named in the folded header too.
- **Computer load** — CPU, memory, GPU, video memory: the whole machine's and the generator's own. The header says
  the share of the CPU the run has.

**On the right**, three tabs, the plan taking the whole right side:

- **Scheme** — the plan from above or at a slant, with the edits on it (stairway annexes too, and, at the
  destruction stage, every crater, breach, fallen ceiling and debris pile as it is built) and, at the light stage,
  how the map is lit. The buttons over it: draw it or not, the view from above, the 3D view, the storeys up to which
  height, and «Full screen» — the scheme on the whole screen, the program's window hidden. **«What the scheme
  shows»** (folded) explains the signs in an even table: the edits (being tried, refused, accepted, base changed),
  what is still in the plan, the map's colours (floor, water, lava, slime, lifts and doors) and the items (weapons,
  armour, health, ammo, power-ups, spawns, teleporters). Hover a sign for the detail, e.g. «a refused edit - red,
  fades in 10 seconds». The mouse controls are there too.
- **Parameters** — the parameters the run was started with, in the same cards as on the Generate page, to look at
  only.
- **Detailed log** — the lines the generator writes.

**The stages on the scheme.** Each stage shows on the scheme itself:

- **The base's frame changing** — the scheme shows the base itself easing into its new shape and back while the
  generator tries the frame. Its parts are tinted apart, the orange lines are the parts' edges, the item signs move
  with the map. The words at the top right say the size and the parts' spread.
- **Light and visibility — the visibility.** The portals between the map's parts show: cyan not worked out yet, green
  worked out. The wave spreads from a spawn; along its front an «eye» walks with cyan sight lines to the portals
  checked next, the ones just reached marked by widening rings. The words say how many portals are done of how many.
  The 3D view shows it best: from above many portals stand edge-on.
- **Light and visibility — the light.** Each lamp of the map glows in its colour; rays spread from the lamps as the
  direct light is worked out, and the glow pulses through the bounced light. Spotlights show where they point. The
  words say how many lamps and how much is done.

![Full screen](screens/en/run_full.png)

On the full screen, «Back to the Studio» (or Esc) closes it and brings the program's window back.

The buttons at the top right:

- **Pause** / **Resume** — the generator stops where it is and goes on from there.
- **Stop** — the run is interrupted; it can be resumed later from the same place on the Generate page (a card
  «An interrupted generation» appears there with «Resume» and «Delete»), when «Keep the accepted steps on the disk» is on in the settings.
- **Cancel** — the run stops and all its working files are deleted.

When the map is ready the program says so and puts the map into the library; the message says how many checks
passed. It is a warning only when the map cannot be played (see «The library»).

### When the generator refuses

First of all the generator turns the base map back into its source and builds it again, to change that copy later.
When the copy differs from the original it leaves such a map alone and says in what: for example «what is drawn on
the walls» — with the generator's exact words under it. The same goes to the log.

## The library

![Maps](screens/en/library.png)

«Maps» shows every finished map as a tile. Over the cover — the map's base and how far it differs from it (for a map
from scratch — «from scratch»); under the cover — its name, when it was made, its size and its checks:

- green **«checks passed»** — all passed;
- grey **«checks: 89 of 93»** — something did not pass, but the map plays: mostly measures of taste (the share of
  corridors, the textures' colour, the number of sight lines) or a planned edit the generator could not build;
- red **«cannot be played: N»** — only when a check failed that play needs: a spawn point in a wall or one that cannot
  be stepped off, a lost pickup or a spawn under a moving part, a place one cannot get out of, a major item out of
  reach, fewer spawns than asked.

«Find by name or base» leaves only the maps that match. The tiles are sized by the «Size» slider or by the mouse wheel
with Ctrl held. «Add a map» (top right) brings any map from the disk into the library; «Refresh» rereads the folder;
«Open folder» opens it in Explorer.

![A map](screens/en/map.png)

A click on a tile opens the map. At the top its name and the same marks (base, difference, checks); on a wide window,
beside the name, its facts (made, size, base, difference from the base or the build's time, how many checks passed)
and the buttons. Below on the left the cover across the column, the shots and the description under it; on the right,
level with the cover, the checks. On a narrow window it all goes in one column.

- **Description** — the base it was made from (or what was asked and what came out, for a map from scratch), the maps
  that gave rooms, likeness and variant number, what was built, how long the run took.
- **The map's checks** — the header says «N of M passed»; the failed ones come first, each with what was measured and
  what it should be, in words: e.g. «floor burnt white 2.0 % (people's maps 1 % at most)». A check play needs is marked
  «- cannot be played».
- **Check again** (a map from scratch) — measures the finished map anew with this Studio's checks: a minute or two, no
  generation. The generator's own checks stay as they were.
- **Shots** — a click opens a shot large; the arrows page through the rest, Esc closes; any shot can be made the
  cover. «Make the cover» starts the game on the map, takes a few views and closes it; «Choose from a file…» takes a
  cover from your own picture. A map from scratch's covers show its jump pad and teleporter when it has them.
- **Play** — starts the game on this map. Your game settings are not changed.
- **Copy into the game** — puts the map into your client's maps folder.
- **Show file** and **Prepare a zip of the map** — an archive for a server: `baseq2/maps` and `baseq2/textures`,
  everything the map needs.

## Settings

![Settings](screens/en/settings.png)

The settings are laid out in cards, in columns by the window's width (up to three): Look, Game client, Folders, CPU
load, Memory and disk, Updates.
Each setting is a row: on the left what it does, on the right the setting itself.

- **Look**: language (Russian or English), theme, «Page at start».
- **Folders**: finished maps, map sources, temporary files. Any can be changed or set back to «Default».
- **Game client** — the folder with the game that holds `baseq2`.
- **Python for the map checks** — which Python the program uses; it can be installed or pointed at here too.
- **CPU load** — what share of the CPU the generator may take by day and by night, and which hours count as day.
  The generator never takes more; the rest stays yours.
- **Memory and disk** — how much free memory the generator's working files may take (the disk is then hardly used),
  and whether to «Keep the accepted steps on the disk» — without them an interrupted run cannot be resumed.
- **Updates** — «Check for updates automatically» (on) and «Check for updates». When GitHub has a newer version, the
  program shows its number and all the changes (newest on top) and asks: «Yes» downloads, checks and installs it
  (your maps and settings stay; the program restarts and shows «What's new»), «Cancel» — not now, and it asks again
  at the next start.

The settings are kept in a file beside the program; where exactly is written at the bottom of the page. The window
keeps its size and place there too: it opens where it was closed, and on the first start on a wide screen —
maximised.

## About

![About](screens/en/about.png)

The program's version and «Check for updates» (top right), what the program is, where it and its settings file
are; below, the versions' history as cards: what changed in each, the newest on top and marked.

## When something is wrong

- **«Game client not chosen»** — point the settings at the game folder; it must hold a `baseq2` folder.
- **«Generator not found»** — there is no `engine` folder beside the program. Unpack the build again, whole.
- **«The map's checks were skipped: Python was not found»** — press «Install Python» on the home page or in the
  settings (or «Point to Python…» when it is installed) and start the run again; the map does not change, only the
  checks appear.
- **«The map failed: the generator could not rebuild this base map exactly»** — the message says in what the copy
  differs from the original. Such a map cannot be a base yet; try another.
- **The run was interrupted** — the Generate page has a card «An interrupted generation» with «Resume».
- **The generator crashed** — the program shows where the crash record lies; send it to the developer, and resume
  the run from the same place.
- **A map says «checks: 89 of 93»** — it plays; what did not pass and why is said on the map's page under each failed
  check.
- **A map says «cannot be played»** — its page shows which check failed and where (a spawn point not in the open, for
  one). Better make it again with another variant number.
- **A map from scratch made by an older Studio** — «Check again» on its page measures it with this version's checks.

## Where the files are

- Finished maps: the «Finished maps (.bsp)» folder of the settings; by default `data\bsp` beside the program.
- Descriptions, covers and shots: `data\descriptions`, `data\covers` (the game's shots are kept as JPEGs - a tenth
  of the PNG with the same look; the shots of earlier versions the Studio recompresses itself after it starts). The
  covers' small copies for the tiles are in `temp\thumbs`; they may be deleted, the Studio makes them again.
- A run's working files: the «Temporary files» folder; after a finished map they are deleted, and a small report of
  the run stays in `data\runs\<map name>`.
- Settings: `MapgenStudio.ini` beside the program.
