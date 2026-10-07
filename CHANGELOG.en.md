# MAPGEN Studio by ly — change log

## 2.5 — 07.10.2026

- Destruction is a stage of its own on the run's page, with its time; its percent is named in the plan's line
- The map's scheme names stairway annexes and, at the destruction stage, shows every crater, breach, fallen ceiling and debris pile as it is built
- The Studio maximised comes back maximised after «Back to the Studio»
- «Start generating» works on the first press (two tooltips were opening over it at once)
- A generation from the Studio keeps off the processor cores Windows reports hardware errors for

## 2.4 — 07.10.2026

- Destruction looks more natural: cracks as a non-repeating network and not on every wall, more where it was hit; holes, craters and soot one by one, each in its place, not a pattern over the wall
- Debris are irregular pieces of what broke (floor, wall, ceiling), not identical bricks; they lie by walls, breaches and falls, never on steps
- Damaged surfaces are drawn at the same quality as the game's other textures
- The texture pack: striped panels and planks are no longer taken for stone
- Fallen ceilings only under a real ceiling, never under the open sky; nothing is built by water
- The generation keeps off the processor cores Windows reports hardware errors for: the generator's crashes on such a processor stopped
- Stairways stand flush against the wall, no slot; a wall standing over a void is no longer chosen
- Light: carried rooms' lamps take their original's colour; tunnels lit by glowing panels settle faster; after the rooms' light is set the map's shared light is checked once more

## 2.3 — 06.10.2026

- «Stairway annexes» (0-10): flights of steps along rooms' walls to new landings, a pickup on each or a ledge it meets; sites found on any base
- «Destruction» (0-100 %): cracks, rubble, craters, breaches, broken edges, fallen ceilings, blocked places - more with the percent; the starts are always free
- The generator's texture pack: surfaces made from the supplied pictures, samples from the web and generated cracks and craters, in the game's format
- Light: a room carried whole with its own lamps is no longer lit twice; tunnels with hung lamps get less fill light; the first map of a new base is lit right

## 2.2 — 06.10.2026

- Updates: «Check for updates automatically» (on) and «Check for updates» in the settings and in About; the new version and the whole change log from GitHub in the Studio's language; «Yes» downloads, checks, replaces the program and restarts it, your maps and settings stay
- After an update, a «What's new» window with this version's changes and the whole log

## 2.1 — 06.10.2026

- The first release on GitHub: the zip works on its own - the generator, the map compiler and the checks' programs are inside, no C compiler needed

## 2.0 — 06.10.2026

- The author's credit «by ly» in About, in the guide and on GitHub - as Q2PRO-X has it
- The generator's and the Studio's sources are published on GitHub: github.com/Quake-Journey/MAPGEN
- The guide says that a map from scratch will come in a future version

## 1.9 — 06.10.2026

- A user guide in Russian and English, with screenshots the program takes of itself
- The Studio finds the map checks in a tools folder beside itself - a downloaded build needs no sources
- The home page says whether Python for the checks was found; Python is also looked for where its installer puts it without «Add to PATH»
- Skipped checks say why: no Python, or no folder with the checks
- With no Python the Studio offers to install it (the official installer from python.org, its signature checked, no administrator) or to be pointed at it; the choice is in the settings too

## 1.8 — 06.10.2026

- While the map is on the whole screen the Studio's window is hidden - Alt+Tab no longer flips between the two
- «Back to the Studio» instead of «Minimise» (and Esc): the map closes, the Studio is back on screen and active

## 1.7 — 06.10.2026

- New sliders «New water», «New slime», «New lava»: by default the generator decides; 0 - none of that liquid; 100 - every room it can fill (slime and lava away from the starts)
- With much liquid asked for, the generator tries the floods first so the run's attempts reach them

## 1.6 — 06.10.2026

- Maps that keep their invisible trigger zones with their faces (q2duel1, say) are no longer refused as a base: the copy is not compared with the original on what nobody sees
- When the generator does refuse a base map, the Studio says which parts of the copy differ from the original and the generator's exact words - in the window and in the run's log
- A torch and every other carried piece keep the picture on their faces after a turn and a move

## 1.5 — 05.10.2026

- Rooms of the second map are carried as a whole cut: ceilings, walls and floor come with what hangs on them; pieces that rest on nothing are left out
- The generator finds the base's wall lamps and repeated wall ornaments and hangs the same on its tunnels' walls
- New option «Wall decorations»: default, none, few, many, very many

## 1.4 — 05.10.2026

- The generator no longer builds its own empty box rooms: new rooms are real rooms of the second map and of the base, carried whole with their walls, openings and detail
- The generator keeps clear of the base's panes, doors and lifts - no new wall lies against them
- «Done of the plan» counts the rooms of the second map and of the base

## 1.3 — 05.10.2026

- New rooms are no longer one square box: proportions, a flat floor, a rim or a gallery with steps, the pickup on a dais, by the far wall, on the gallery or between columns, columns and trims - no two alike in a map
- The second map gives architecture: a room of it is built in the rock beside the base, with its own columns, steps, trims and light
- Some new rooms take the second map's skin
- The end says what was taken from the second map, or why nothing, by count
- The run's log is kept with the map; the map's checks no longer fail for the run having worked in memory

## 1.2 — 05.10.2026

- The plan shows the map being built with its accepted edits while it runs - it showed the base before
- Faint blocks on the plan show where the edits not yet tried will go: passages and annexes, bridges, pools and liquids, windows
- «Done of the plan»: how many passages, annexes, two-storey rooms, bridges, pools, windows and liquid changes are accepted
- The visibility and light passes in percent - on the stage and on the plan; after them the plan shows the map in its own light
- The plan's feed shows the run's stages too, not only the edits

## 1.1 — 05.10.2026

- The map and shot tiles grow with Ctrl and the mouse wheel or the «Size» slider - pictures and captions together
- The tiles take the window's whole width; the page's top with its buttons stays put
- A click on a shot shows it over the whole window: forward, back, close; «Make it the cover» there

## 1.0 — 05.10.2026

- A generation not wanted is deleted with «Delete» - with all its working files
- «Cancel» stops a running generation and deletes its files at once
- After a generation that ended well its working files go by themselves - the map is in the library
- Before deleting the Studio asks and says how much space it frees

## 0.9 — 05.10.2026

- The generator keeps its working files in memory, not on the disk: about 2 MB written per generation instead of 30
- Settings «Memory for the generator's working files» and «Keep the accepted steps on the disk»
- A generation without its steps on the disk is not offered to resume, and the Studio says why
- The load card shows the graphics card and its memory
- The full-screen plan is no longer cut, its marks stay on the map

## 0.8.1 — 05.10.2026

- The plan is drawn by the graphics card - smooth on the full screen too
- The events on the full screen sit under the run's lines, not over them
- «Full screen» brings an open one forward

## 0.8 — 05.10.2026

- The plan of the map being built in 3D: turn, zoom, full screen
- The load card: processor and memory - of the computer and of the generator
- Creative options: new passages, annex rooms, two-storey rooms, bridges, halls
- Liquids made other liquids (water, lava, acid) - their look and their harm
- The ticked bases and the whole form kept across starts

## 0.7 — 05.10.2026

- The window no longer hangs while a generation runs
- The detailed log reaches the window's bottom
- Each stage's time and the whole run's, the stage's end and the edits left
- A pause stops the clocks; a failed run's stages marked as they were

## 0.6 — 04.10.2026

- Bridges between galleries across an arena
- New rooms lit the way their base lights its own
- A new base's light fitted once, by itself
- The day and night share of the processor - of its fast cores

## 0.5 — 03.10.2026

- The light pass on every fast core of the processor
- Each base's light calibrated for it
- The Studio is one file, no libraries beside it

## 0.4 — 03.10.2026

- Quake III layouts as bases (cor, q3t2)
- The start page chosen in the settings
- A generation another Studio window carries is not taken for an interrupted one

## 0.3 — 03.10.2026

- Any Quake II map as a base, several at once
- The generator's refusals in plain words

## 0.2 — 03.10.2026

- Generation from the Studio, an interrupted one resumed where it stopped
- Map covers shot in the game by themselves
- The map library with descriptions and checks

## 0.1 — 03.10.2026

- The first version: the shell, light and dark themes, Russian and English
