# MAPGEN Studio by ly — change log

## 3.33 — 13.10.2026

- A generation ends 3–5 minutes sooner again: the final measure of difference takes the walks of the map the run already made instead of walking it twice more (a fault of 3.32)

## 3.32 — 13.10.2026

- The plan's word «up to N %» is closer on maps made larger: it leans on the trial builds of the largest digs and promises no more than they measured (q2dm1: 64.6 % against 57.4 % reached before, 59.1 % now)
- A map grown to its full height is no longer given up when its base is rebuilt: for one «flat» piece and fractions of a pixel in the textures of slanted walls the generator went on, without a word, with the map at its usual size
- On a map that tall edits are accepted again: the measure of difference and the walk hold a map as large as the game's whole space
- Players' starts on a map grown tall stand at their own height over the floor instead of rising with the map

## 3.31 — 13.10.2026

- A large map stands at its full height on the first try: q3t2 made ten times larger grows as tall as it grows wide (3.1 times; it used to reach only 2)
- «Ceiling height» is no longer given back whole when the map meets the limit of the game's coordinates: the ceilings rise as far as the game allows, and the run says how much was given
- A large map's light: the size of the light patches and the room for the lightmap are chosen beforehand from the map itself - no trial passes that ended in an error
- Flights of low steps on a map grown tall get their ramps where an unseen barrier stands beside them too
- Pickups that stood one over another in the original map still fall to the floor on the grown map and can be reached

## 3.30 — 13.10.2026

- The generator no longer loses a piece whose trial build fails alone but builds after its neighbour: it is built again at its turn (q2dm3 lost a tunnel with a lift this way)

## 3.29 — 12.10.2026

- On maps made larger the windows stand in every wall that can hold one again (six walls on q2dm1, not one): the generator finds whose room a narrow space behind a wall is
- The plan's word «up to N %» is closer: a dig whose trial build failed, would leave a machine nobody can reach or would lose a pickup is no longer counted, nor built a second time

## 3.28 — 12.10.2026

- In the «Ruin» card the slider runs the card's width

## 3.27 — 12.10.2026

- In the «Ruin» card the words run across the card, the slider under them

## 3.26 — 12.10.2026

- The generation page: «Base map» is as tall as the two cards beside it; when the maps do not fit, its list scrolls inside it
- The generation's options are cards by group with their names: «The base's frame», «New rooms», «The base rebuilt», «Water, slime, lava», «Ruin», «What may change»; the cards of a pair are one height

## 3.25 — 12.10.2026

- The generation page: «The new map» and «The finished map» stand to the right of «Base map» and no longer slide down when the list holds many maps
- The list of base maps shows eight maps; with more it scrolls inside its own card
- The generation's options are in two columns under them: the page is shorter

## 3.24 — 12.10.2026

- Fixed: after the light pass ran again on a very large map the starts, pickups and lights were lost - the map keeps them now
- A later round's edits (walls moved, blocks, floor shifts) no longer land on what the generator built in earlier rounds: a storey's flight no longer runs into a wall
- The finished map's checks see the annexes, storeys and stairways of every round, not of the first alone
- A start the generator moves stands on the floor, not sunk into it
- A loading window: at start it shows at once how much is done and what is being done
- The Studio opens in a second: the home page and the library show small copies of the covers, not the full shots
- The game's shots are kept as JPEGs - a tenth of the room; earlier shots are recompressed by themselves after the start
- A «Community» block on the home page: the news, the community group and the site

## 3.23 — 12.10.2026

- Very large maps no longer come out unlit: when the light pass hits its limits the generator runs that step again with larger light patches and more room for the lightmap - the visibility is not worked out again
- A map made larger grows as tall, in proportion: the steps and ledges that could not be climbed any more get gentle ramps or small flights in front of them, the gaps in gratings a player could not fall through are bridged, lifts and jump pads follow the new height
- When full height leaves a map unwalkable somewhere, the generator tries a little less height until the whole map walks

## 3.22 — 11.10.2026

- The generation page reworked: on the left what matters - how far the map already differs from the base (large), the edits (accepted, builds, considered, time) and the plan as a table with progress bars; on the right the map's scheme the window's whole height
- The stages, the computer's load and the scheme's legend are folded away; a folded section's header still says the gist - the stage now, the CPU share
- The stage under way and its time as a coloured badge under the map's name: blue running, yellow paused, green done, red failed
- The scheme's legend as signs with short words, drawn as on the scheme itself
- When the map's name is taken (the library has such a map, its records exist, it is running or was interrupted), «Start generating» asks: overwrite, correct the name, or cancel. «Correct the name» puts the cursor in the name field at once
- A new look for the whole program: the menu on the left with large coloured signs lit under the mouse; every page in cards, two columns, with large heads
- The home page: two paragraphs on the Studio and its generator, «New map», «Maps», «Guide», the latest map with its cover, readiness, links to the guide that comes beside the program, and a map in four steps
- While a run goes on, its strip stands over every other page: what it is doing, the difference from the base, the edits, the time and «Open the run»
- The generation's settings in cards; at the foot always the summary («the map … will be made: base … likeness …») and «Start generating»
- Maps: search by name or base; over the cover the base and the difference from it, under it the checks in colour; a map's page in cards
- Each stage shows on the scheme: the base easing into its new frame; at «Light and visibility» the visibility's wave with its eye and sight lines, the lamps' glow and rays
- «Light and visibility» no longer stands at 100 % through the whole last, longest tenth: 90 % now reads 90 %
- The two-storey room on stretched q2dm1 no longer puts its doorway on a wall top under the base's invisible clip - its upper floor is reached

## 3.21 — 11.10.2026

- The two-storey room on stretched q2dm3 is no longer refused for a tiny crack the map's build left far from it, in a wall the change never touched; a crack near the change itself is still refused

## 3.20 — 11.10.2026

- Two-storey rooms: the generator finds room for them more often - also where both doorways face the same way, and as a room with one doorway - up to two a map (two on stretched q2dm1)
- A room thrown away before because of the sky over a courtyard is now fitted: its doorway is lowered under the sky and the room is checked to build before it is planned
- Annexes and rooms that reach above a roof no longer open the map to the outside: the void past the walls under the lifted sky is closed, and the sky of rooms already built is left alone
- Every kind of window on each map: fixed, dropping when shot, opened by a plate on the floor. Windows in different outlines - rectangular, round or oval, arched, with a transom and a vent - and with different glass: pale, blue, wired, amber, olive, smoke
- A wall moved back over a floor piece that ended short of it no longer leaves a hole to the outside
- The plan's promise is truer: every place of the map is counted once, and a large change the build would refuse anyway is checked beforehand and not promised

## 3.19 — 11.10.2026

- On a stretched base every drawn face wears its texture again: sides the original map never drew could carry texture axes along the face itself, and stretched such a face showed no pattern (on q2dm3 one by a pool). Such axes are now built anew from the face's plane

## 3.18 — 11.10.2026

- An annex gets a valuable pickup even when the generator cannot find a walk to it (on q2dm3 the railgun, launcher, quad and megahealth stand on the top tier the trains carry players to): the most valuable pickup nearby is taken, and the player's walk checks it is still in reach after the move. On q2dm3 the second annex holds the quad instead of the machinegun

## 3.17 — 11.10.2026

- The finished map's check «the chaingun is in the map» no longer refuses a map made from a base that has none (q2dm3): it catches a chaingun lost, not one that never was

## 3.16 — 11.10.2026

- A window can no longer look into rock: an edit that puts a wall or a block right in front of a window already cut (on q2dm1 a block and a moved wall stood so) is now refused

## 3.15 — 11.10.2026

- A player's start can no longer end up over the floor: an edit after which a start would hang (on q2dm1 a stairway and two wall reshapes moved one, and the player dropped a step at spawn) is now refused
- A room reshape whose wall stood on the void (at the room's corner or at the wall's end) no longer opens the room to the outside: a slab goes under the strip it gives up and at its ends. On q2dm3 at 150 % one such reshape in three failed its build, now one in fourteen

## 3.14 — 10.10.2026

- The finished map's «water» check no longer counts as «standing water» the side of a pool a sealed pocket of the void lies against: such a pocket is left behind a long tunnel, nobody can get into it or see it - the generator counts it so too
- q2dm3 with your options on a 150 % base: in 25 minutes the map differs from its base by 44.5 %, the plan said up to 50 %. Three of the four large edits went in: the long tunnel with its halls and two annexes

## 3.13 — 10.10.2026

- The plan's largest edit - a long tunnel with halls - is no longer thrown away for «standing water» in a pool far off: the tunnel through the void round the map cut a piece of that void off, and the side of a pool nobody can come near was counted as water standing in the air. On q2dm3 with your options this one edit gives about 37 % difference
- The finished map's «water» check knows the liquid's upright faces the original map had by their place, not by their texture: an edit that turned lava into water no longer makes them «new»

## 3.12 — 10.10.2026

- On a stretched base edits are now built instead of thrown away: an annex no longer leaves a gap to the outside by a wall the stretch laid off the grid; a doorway gets a sill where there was no floor under the wall; a ceiling grown to a wall moved back no longer stops at the old corner
- A room holding a pickup that was out of reach on the original map too is no longer counted lost after an edit at the other end of the map: on q2dm3 at 150 % one edit in five or six was thrown away for it. With the fixes above: on q2dm3 with your options the same 25 builds make a map 12 % different from its base instead of 5 %
- The finished map's checks (pickups, glass, water, stairways, rooms' light) hold it to the stretched base it was built on, not to the original map's old places

## 3.11 — 10.10.2026

- A generation started without the window (from the command line) now takes the window's own settings: the edit options, the base's frame and the generation's time

## 3.10 — 10.10.2026

- «The base's frame»: a new slider «Shift of the parts», 0-100 %. The map's parts slide sideways against each other: the rooms of one part stand moved over against the next one's, the passages between them bend - another layout of the rooms. Floors stay level, walls upright; parts with doors, lifts and trains move whole, not skewed. q2dm1 shifted by 60 % passed the check on the first try
- The lines the base is cut along are now placed away from the walls' ends: no thin scraps of wall are left, which could make a stretched base fail the rebuild check
- If a stretched base still fails the rebuild check, the generation's events say why

## 3.9 — 10.10.2026

- «The base's frame»: a new choice «Turn of the base» - turn the whole map by 90°, 180° or 270°, mirror it, or «By the seed». Doors, lifts, trains, jump pads, the players' facing at the start and the textures turn with it. If the turned map does not pass the check, the generator keeps the stretch but not the turn: on q2dm1 it is so because of two pickups on pedestals only a rocket jump reaches
- «The base's frame»: a new slider «Ceiling height» - 100 to 200 %. Everything above the highest place a player can stand is lifted: the top level's halls and the sky grow taller, floors, steps and jumps are untouched. q2dm1 with its ceilings half again higher passed the check on the first try
- The stretched base is checked once, before the first edit: the map's description says whether it was turned and how much the ceilings were lifted

## 3.8 — 10.10.2026

- On a larger base new passages may run longer - as many times as the map grew. On q2dm3 with your options and a size of 150 % the plan gives 4 large edits checked before any build (annexes, passages, a two-storey room) - on the base as it was there were 2; the plan says up to about 50 % difference
- When a stretched base does not pass the rebuild check, the generation does not stop: it goes on the original base and says so

## 3.7 — 10.10.2026

- New: «The base's frame». The generator now first changes the base itself, and only then builds onto it: it cuts the map along its length and width into parts and stretches or squeezes each in its own way - one room becomes twice as long, the passage beside it shorter, the yard wider. Heights do not change, so the steps, ledges, jumps and lifts stay as they were. The generator places the cuts itself and never through doors, lifts, trains and their paths
- Two sliders: «Map size» - 10 to 1000 % of the base's area, and «Unequal proportions of the parts» - from 0 (the whole map stretched evenly) to 100 % (some parts several times longer than others). By default 150 % and 50 %. The map gets as much as it can take: no passage is squeezed narrower than a player, and the map stays inside the limits the game holds
- The stretched base is built and its walk checked once, before the first edit - about a minute. If the check fails, the generator tries a milder one. For example: q2dm1 three times its area, parts stretched from 1 to 3.5 times - built and walkable on the first try, every pickup in reach
- The plan's word before a generation is now counted the way the difference from the base itself is: new rooms join both what changed and the whole map. On your map mg_10_6695 the plan says about 32 %, and 27 % was reached; before it said up to 50 %
- The time slider's label no longer runs together: «Closer» and «up to 120 min» stand apart

## 3.6 — 10.10.2026

- At the end of a generation and in the map's description: how the edits went - how many did not fit the map and how many were refused by the check before the build, how many had been tried and were not offered again, how many were built and for how many the walk was worked out whole
- A train platform's path is kept clear along the segments it runs, not the whole box round its path: inside a train's loop the generator may build again

## 3.5 — 10.10.2026

- Generation is several times faster: after each build the walk is worked out again only around the changed place, the rest is taken from the last check, and the answer is the one the whole check gives. On edits of your map mg_10_6695 this check runs 7-10 times faster
- Every edit is checked before it is built: one that buries a place a player climbs by is refused at once, with no build. On the ledger of mg_10_6695 this would have kept back 69 of the 72 builds that were spent for nothing (about 83 minutes), and none of its 64 accepted edits
- An edit refused once is not tried again in the later rounds. When there are no new edits worth building the generation says «the plan ran out» and finishes the map
- Liquids are swapped at the end of a generation: they add no difference from the base, and used to take up to an hour
- The most valuable edits are built first - new rooms and stairways, windows and blocks last. Before its first build the generation says how much difference the plan gives at most with the builds left
- «Faster ↔ Closer» sets the generation's time: 15, 30, 60 or 120 minutes. When the time is up the map is finished, and its description says how much difference was reached in that time and how much the plan gave

## 3.4 — 10.10.2026

- New architecture no longer stands in the way of lifts, doors and train platforms: the generator keeps clear of their whole travel, not only of where they rest, and refuses an edit after which a machine loses any of its room (on the last map a train platform rode through a new wall)
- The generator takes 4 more maps as a base (111 of 128): a pickup hidden deep in rock is left out of the copy; a key repeated in an entity reads as the game reads it; an invisible tool texture is no difference; machines' boxes are compared within a unit
- The run's difference line in plain words: «The map already differs from the base by N%, M% is asked (the more, the less like the base)»
- The edits' time left counts the item swaps and rooms of other maps that follow the main builds (it used to stand at «0 s» for minutes); the progress line says «then item swaps and rooms of other maps: k of n»

## 3.3 — 09.10.2026

- The generator takes almost any map as its base: 107 of the game's 128 maps are taken (it was 75). A map is no longer refused for textures its own original lacks in this game, for empty pieces of geometry, for layers of glass the new compiler does not draw, or because lifts and doors with a box ending at zero read as not matching
- When the generator cannot take a map as its base it says why: which texture was not found, what the map compiler said

## 3.2 — 09.10.2026

- The q2dm6 base is taken: the generator rebuilds its sloped rocks exactly (their points used to go out a billion units and a slope was lost) and the textures of lifts and doors with an origin of their own (their shift was counted twice) - a generation on q2dm6 no longer stops at building the base

## 3.1 — 09.10.2026

- The right button's «Copy» menu is seen now: select a text with the mouse, press the right button - «Copy the selection», «Copy» the whole text and the other lines (the menu used to open empty and unseen)

## 3.0 — 09.10.2026

- Nothing rebuilt stands against the sky any more: a moved wall, a column or a block stops under the sky, and an edit whose support would be the sky itself is not made (on the last map, walls set on a roof hung in the sky)
- A second floor at tall walls: where a wall has no tier of its own, a gallery is built along it on corbels into the wall, a flight along the wall up to it, a pickup at the gallery's far end
- The ruin keeps clear of lifts and doors over their whole travel, not only where they rest: no stones, chunks or patches in a lift's shaft
- A map can be played while the game is already open, and a cover is taken beside the open game (the Studio used to wait for the game to close and gave the cover up after 10 minutes)
- The right button's «Copy» menu opens once the button is let go, and from the menu key; what happens to it is written to ui_clicks.txt beside the program

## 2.9 — 08.10.2026

- Remodels of the base: the generator changes the base map itself, not only builds onto it - a room's wall moved in, a wall turned at an angle, a terrace with steps raised along a wall; the arena first. A new option «Remodel the base»: «Default» (by the likeness), «None» or 1 to 16
- Blocks in the base's rooms: a box, an L, a cross, an octagon or a round one, of different sizes and turned at different angles, low ones to climb, high ones a cover; against a wall or free, in the room's own material, the arena first. A new option «Blocks in the rooms»
- The base's floor changes: daises stepped on every side are raised, channels across the floor are sunk with a flight at both ends (only where no other room lies under the floor). A new option «Floor: daises and channels»
- The base's stairs are rebuilt between the same two floors: the old flight becomes a landing, reached by a half-round foot of steps or a side flight. A new option «Rebuild the base's stairs»
- On the generation's scheme everything that changes the base's own architecture (a remodel, a wall moved or turned, a new opening, a window, a pit, a floor level changed and so on) is drawn teal and labelled while the edits go on (then it fades as accepted annexes do); the feed says «rebuilt: …»
- Any text of any Studio window is selected with the mouse - a drag across it, or a double click for the whole of it (a map's name, say) - and Ctrl+C copies it; the right mouse button over it - «Copy» (the selection, the text, its whole block or the whole window's text); the scheme's words too
- The destruction's debris and stones no longer hang in the air: they are laid only on floors a player reaches from the spawns, and only on real rock - not on a sky's top or the edges of high walls
- The generation does not stop after four rounds of the plan while trial builds are left and the base offers new edits
- Edits that cannot apply on this map (a widened passage, a reshaped room, a turned section) are dropped when the plan is made, with the reason - they used to take up to three quarters of the tries
- The map's description says truly why the generation ended: when builds were left but the plan ran out, it says so, with the builds counted; and it explains what «difference from the base» counts
- The map's description has «Asked and made»: for annexes, storeys, bridges, remodels, blocks, the floor and the stairs - how many were made of those asked and why not more; an annex left without a weapon or armour gets ammunition or health; when the asked annex size has no more room, smaller annexes (256-384) are built, and it is said
- The base's own changes are dealt before the stairway annexes, larger in the arena: walls moved up to 256 and buttresses from 64 long, daises up to 384 across and 96 high, terraces up to 96; some of the arena's blocks are columns from floor to ceiling. Pickups and spawns before a moved wall go forward, on a dais they rise to its top. On q2dm1 at your options the arena's own architecture changes by 16-19 % on every variant tried
- Stairway annexes lead only up, to where the way round is long: a tier, an opening or a gallery over a room's wall. The flight runs along the wall and follows its pilasters and recesses (the recess behind the steps is filled); a high climb is broken into flights with landings; where the wall is short, the first flight comes from the room and turns at the wall. No more flights to a landing with a pickup in a room's middle, no free-standing platforms; pickups and spawns where the steps go are lifted onto the steps
- Item annexes no longer have tribunes (a dais in the niche)
- More columns, and different: two side by side carry a beam, a lone one either holds a piece of the roof or has fallen - a stump and its drum lying beside it
- The base's changes (remodelled walls, blocks, daises) spread over the whole map: the arena gets at most half, the other rooms the rest

## 2.8 — 08.10.2026

- Destruction up to ×100: the slider's right half is the factor, ×1 to ×100; past 100 % the 3D ruin grows - stones and debris (on open floor too), craters, breaches, broken edges, falls and blockages, as much as the Quake 2 map format holds (on q2dm1 about 3-4 times what 100 % makes, on a small map far more); the cracks and stains stay as at 100 %, no new textures; the map's description says how much 3D ruin was asked and how much was built
- Pools of water, slime and lava are not dug under the new stairways (on a map with lava one stairway had lost its steps)
- «Faster ↔ Closer» beside the likeness: how many trial builds a generation may spend (15 to 140, the middle 45 as before), with a rough time beside it. When the difference asked for is not reached, the map's description says the builds ran out
- The order after the generation: the map's checks first, then the destruction (when asked), and the light is set and checked on the finished - ruined - map. The light used to be set before the destruction, which then changed it
- In a map opened in the library - «Prepare a zip of the map»: an archive for a server, baseq2/maps - the map, baseq2/textures - every texture of it the standard game does not have (the destruction, debris), and its sky if it is its own; where to save it, the save window asks, then the file is shown in its folder

## 2.7 — 07.10.2026

- The map's checks judge exactly the plan the generation made: every option goes into its record (passages, annexes, storeys, bridges, halls, decor) - before, only the stairways and liquids
- The destruction leaves the generator's own building whole: stairways, annexes, galleries and bridges
- The map's description says how many platforms with stairs stand after the destruction, and why the rest do not
- Stairs go against walls first; standing free only in rooms whose walls have no place. A flight may stand by an uneven wall: the gap behind it is laid solid
- A stairway's steps and sides are of the room's floor material, not of a wall of lit panels
- Lava and slime: the larger share asked takes its rooms first; a pool keeps the climb places dry instead of being refused for a blocked way; a liquid not laid is said with why
- Carried rooms with one or two lamps get the room's own as well; a copy is judged by its light's spread too; cracks darken a wall by 10 % at most
- When a run could not go on from where it was and began again, the Studio says so

## 2.6 — 07.10.2026

- The map's light and its checks work on any computer: they looked for the game in the developer's folder, and on other machines the step never ran
- Acid and lava appear when chosen: a pool draws back from the players' start points instead of turning to water; the map's description says how many new pools of each liquid
- Platforms with stairs both against walls and standing free on open floor, 96-192 up: more of them on the same maps (q2dm1: 7 of 10 asked instead of 2)
- Destruction: a corridor's blockage is a collapsed wall of leaning slabs with gaps, not one solid block; single pieces of debris no larger than 32
- Annexes: niches 128 x 160 - step in and take the item; rooms octagonal, cross-shaped, L-shaped and with rounded corners, not only rectangles
- Rooms carried underground are taken first from lamp-lit ones; a copy of a sky-lit room is checked against the light at its door
- Light: a room lit up by its neighbours is no longer darkened by too hard a step
- The Studio has its own icon - in the window, the taskbar and the window switcher
- The window no longer freezes on the day's first generation: the faulty cores are read in the background when the Studio starts
- A generation interrupted in its checks or its destruction resumes from the checks: the map is built already and is not built again

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
