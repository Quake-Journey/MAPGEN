using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MapgenStudio;

/// <summary>
/// Brief 19 (the PO, 04.11: «новую уникальную карту с интересной геометрией, подходящей для игры с людьми, чтобы
/// параметрами всё регулировалось ... кол-во лестниц, джампадов, лифтов, воды, лавы, кислоты, сколько точек спавна,
/// какое оружие, какие айтемы ... в каком стиле текстуры ... на какое кол-во человек рассчитана карта»): what a map made
/// from scratch is asked to be. Every number is a number; -1 (or empty) is «По умолчанию» - the generator's choice
/// from the player count and the style, and the run's record names what it chose. Kept in the ini as one JSON line.
/// </summary>
public sealed class ScratchParams
{
    public int Players { get; set; } = 2;
    public int Spawns { get; set; } = -1;
    public int SizePercent { get; set; } = 100;        // of the floor people's maps have for that many players
    public int Levels { get; set; } = -1;
    public int SkyPercent { get; set; } = -1;
    public int LongLines { get; set; } = -1;
    public string Shape { get; set; } = "";           // "" default | halves | arena
    public int Lifts { get; set; } = -1;
    public int Pads { get; set; } = -1;
    public int Teleporters { get; set; } = -1;
    public int WaterPercent { get; set; } = -1;
    public int LavaPercent { get; set; } = 0;
    public int SlimePercent { get; set; } = 0;
    /// <summary>weapon classname -> count; a weapon not named takes the player count's default.</summary>
    public Dictionary<string, int> Weapons { get; set; } = new();
    public string Stack { get; set; } = "";           // "" default | ra_mh | ra_mh_quad | mh_adren_2ya | 2ya_adren_quad
    public int ItemsAtHeight { get; set; } = -1;
    /// <summary>null - the player count's default set; else exactly these.</summary>
    public List<string>? Mechanics { get; set; }
    public string Style { get; set; } = "generator";  // generator | maps | mixed | generated
    /* 3.45, the PO 05.11 («нужен подраздел генерации текстур карт с нуля самой студией … параметры для этого задай»):
       the Studio's own textures - "" each means the generator's default */
    public string GenTheme { get; set; } = "";        // "" by the run's number | tech | gothic | industrial | base
    public string GenColour { get; set; } = "";       // "" auto | warm | cold | green | rust | grey
    public string GenWear { get; set; } = "";         // "" worn | clean | worn | dirty
    public string GenScale { get; set; } = "";        // "" medium | small | medium | large
    public string GenRelief { get; set; } = "";       // "" medium | soft | medium | sharp
    public string GenShare { get; set; } = "";        // "" all | all | detail | walls
    public List<string> StyleMaps { get; set; } = new();
    public int Windows { get; set; } = -1;
    public int Fidelity { get; set; } = 70;           // how much the accepted families dress the skeleton (likeness)
    // brief 19 §4, the rest of «всё всё всё»
    public string Mode { get; set; } = "";            // "" from the players | duel | ffa | tdm
    public int VerticalSpan { get; set; } = -1;      // units, floors' p5..p95
    public int CorridorPercent { get; set; } = -1;   // openness: the share of corridors (people's maps: 40)
    public int OpenPercent { get; set; } = -1;       // and of open places (10); halls are the rest
    public int Stairs { get; set; } = -1;            // flights of steps, at least
    public int Ramps { get; set; } = -1;
    public int Ladders { get; set; } = -1;
    public int Drops { get; set; } = -1;             // one-way drops, at least
    public int Doors { get; set; } = -1;
    public int Pits { get; set; } = 0;               // deadly chasms
    public int Shards { get; set; } = -1;
    public int AmmoPerSpawn10 { get; set; } = -1;    // tenths of a box per spawn
    public int HealthPerSpawn10 { get; set; } = -1;  // tenths of a small health per spawn
    /// <summary>The stack «свой»: item classname -> count.</summary>
    public Dictionary<string, int> StackCounts { get; set; } = new();
    public string Decor { get; set; } = "";           // "" default (none) | few | some | many
    /// <summary>The PO, 04.11: rooms flooded over their floor (water standing above its edge) only when he allows it.</summary>
    public bool WaterAboveFloor { get; set; }
    /* the PO 13.11: the scripted pieces (tools/mapgen_scratch_pieces.py, _pieces2.py) - each a count (0 none) */
    public int Trains { get; set; }
    public int Stones { get; set; }
    public int Traps { get; set; }
    public int Rotators { get; set; }
    public int Shutters { get; set; }
    public int PickupWalls { get; set; }
    public int BentBridges { get; set; }
    public int WallSteps { get; set; }
    public int Lasers { get; set; }
    public int Pistons { get; set; }
    public int Pendulums { get; set; }
    public int Trapdoors { get; set; }
    public int Geysers { get; set; }
    public int TurnBridges { get; set; }
    public int Currents { get; set; }
    public int Waves { get; set; }
    public string TrainPath { get; set; } = "";
    public static readonly string[] TrainPaths = { "", "across", "loop", "island" };
    public string StoneShape { get; set; } = "";
    public static readonly string[] StoneShapes = { "", "row", "gaps", "zigzag" };
    public string TrapTrigger { get; set; } = "";
    public static readonly string[] TrapTriggers = { "", "buttons", "plate", "item" };
    public string TrapHazard { get; set; } = "";
    public static readonly string[] TrapHazards = { "", "lava", "slime", "crusher" };
    public string RotatorKind { get; set; } = "";
    public static readonly string[] RotatorKinds = { "", "drum", "flap", "fan" };
    public bool PoolLadders { get; set; }
    /// <summary>The PO 13.11 after the first try: drilling rigs, cogs on walls, blaster turrets, conveyors with crates;
    /// the hammer's head; the straight movers' motion; the hammer's shock wave.</summary>
    public int Drills { get; set; }
    public int Cogs { get; set; }
    public int Turrets { get; set; }
    public int Conveyors { get; set; }
    public string PendulumKind { get; set; } = "";
    public static readonly string[] PendulumKinds = { "", "hammer", "sledge", "spiked", "axe", "labrys", "sickle", "mace", "saw", "anchor" };
    public string PieceMotion { get; set; } = "";
    public static readonly string[] PieceMotions = { "", "even" };
    public bool HammerBlast { get; set; }
    /// <summary>The pieces' speeds and pauses, % of people's (0: 100).</summary>
    public int PieceSpeed { get; set; }
    public int PieceWait { get; set; }
    public static readonly int[] PieceSpeeds = { 50, 75, 125, 150, 200 };
    public static readonly int[] PieceWaits = { 50, 75, 150, 200, 300 };

    public string Sun { get; set; } = "";             // "" by the style | yes | no
    public string Tone { get; set; } = "";            // "" by the style | warm | cold
    /// <summary>The PO, 05.11: how hard the powerups are to get - "" default (mixed) | easy | medium | hard | mixed.</summary>
    public string PowerupAccess { get; set; } = "";
    /// <summary>The stack's armour and mega (and a power shield) taking turns in one nook, as on q2dm8.</summary>
    public bool PowerupCycle { get; set; }
    /* the PO 12.11 (his mg_new_84719: two armours side by side, the railgun a step off them on a floor one walks to):
       «айтемы, оружие, броня, паверапы … должны иметь ценность подбора», «рельса должна быть заслуженной», «плыть под
       водой … за важными целями», «сформировал логику расположения и делал миксы пресетов» - from the knowledge base
       of people's maps (tools/mapgen_item_practice.py, tools/mapgen_item_rules.json) */
    /// <summary>How the prizes (railgun, mega, quad, body armour…) are earned - "" default (people) | people | nooks |
    /// water | exposed.</summary>
    public string PrizeAccess { get; set; } = "";
    /// <summary>How many prizes lie under water (a dive, a swim to a vault) - 0..3.</summary>
    public int Underwater { get; set; }
    /// <summary>How far apart the majors keep - "" default (people: their lower quartile) | wide (their median).</summary>
    public string ItemSpacing { get; set; } = "";
    /// <summary>Whose item practice - "" default (all the maps) | a family (q2dm, q2duel …) | two joined by «+».</summary>
    public string ItemPractice { get; set; } = "";
    public static readonly string[] PrizeAccesses = { "", "people", "nooks", "water", "exposed" };
    /* the PO 12.11 (his mg_new_7775): «никакого глубокого бассейна по типу как на q2dm1 в котором плывешь за рейлом»,
       «на q2dm4 или q2dm5 там вообще многоуровневые конструкции с множеством глубоких водоемов» */
    /// <summary>What the water is - "" default (people: deep pools, two or more joined by tubes under water) | people |
    /// levels (pools on several floors joined by tubes, q2dm4 and q2dm5) | shallow (3.66's pits, waist-deep).</summary>
    public string WaterBody { get; set; } = "";
    public static readonly string[] WaterBodies = { "", "people", "levels", "shallow" };
    public static readonly string[] ItemPractices =
    {
        "", "mix", "q2dm", "q2duel", "q2rdm", "ztn2dm", "omf", "koldduel1", "ptrip", "match1",
        "q2duel+ztn2dm", "q2dm+q2rdm", "q2duel+koldduel1", "q2dm+ztn2dm", "q2rdm+omf", "ptrip+match1", "q2dm+q2duel",
        "ztn2dm+q2rdm",
    };
    /// <summary>3.46, the PO 05.11 (medusa_b1): round shapes - "" none | few | some | many.</summary>
    public string Round { get; set; } = "";
    /// <summary>Which of them: corners, apses, podiums (null - all three).</summary>
    public List<string>? RoundKinds { get; set; }
    public static readonly string[] AllRoundKinds = { "corners", "apses", "podiums" };

    /* brief 25 A4, the PO 06.11 («космическая карта … воздушная, с джампадами и отдельными местами в воздухе … новые
       карты в подобных стилях через отдельные параметры»): the shape «space» - islands in the void. Its own rows, shown
       only when that shape is chosen; -1 / "" the generator's default (mapgen_scratch_space.SPACE_DEFAULTS) */
    public int Islands { get; set; } = -1;           // walk-joined islands: 6..16 (default 8 / 10 / 12 by players)
    public int PadOnly { get; set; } = -1;           // of them reached only by a jump pad, at least (default 2)
    public string Edges { get; set; } = "";          // "" open | open | some (railings in places) | railings
    public int HeightSpread { get; set; } = -1;      // the islands' heights over this many units (default 800)
    public string PadReach { get; set; } = "";       // "" medium | short (≤ 512) | medium (≤ 1024) | long (≤ 1700)
    public string Bridges { get; set; } = "";        // "" some | none | some | many

    public static int DefaultIslands(int players) => players <= 2 ? 8 : players <= 4 ? 10 : 12;

    /* brief 25 B, the PO 06.11 («pro_q2t4 … не типичная архитектура для q2, тоже должны уметь такое строить»): the shape
       «tower» - whole storeys over one footprint round an atrium. Its own rows, shown only for that shape; -1 the
       generator's default (mapgen_scratch_tower.TOWER_DEFAULTS) */
    public int Storeys { get; set; } = -1;           // 2..4 (default 3)
    public int StoreyHeight { get; set; } = -1;      // 160 | 192 | 224 (default 192)
    public int Shafts { get; set; } = -1;            // 1..3 with the atrium (default 2)
    public int Perches { get; set; } = -1;           // 0..3 ledges only a jump pad reaches (default 2)

    /// <summary>The PO 06.11: the single-player game's ships flying over the map, 1..3 (-1 none), any shape.</summary>
    public int Ships { get; set; } = -1;

    /* brief 32, the PO 08.11 («для джампадов - круглых и наклонных нужно чтобы в студии были параметры для регулировки их
       размеров, по умолчанию как сейчас, но можно сделать меньше на 50% либо больше на 200% … по местам спавнов также …
       по телепортам также»): sizes in percent - 100 (the plate: 0, none) is «По умолчанию», as 3.58 built them */
    public int PadDiscSize { get; set; } = 100;
    public int PadWedgeSize { get; set; } = 100;
    public int TeleFrameSize { get; set; } = 100;
    public int SpawnPlateSize { get; set; } = 0;
    public static readonly int[] SizeChoices = { 50, 75, 150, 200 };

    /* brief 33, the PO 08.11 («если генератор применяет что-либо из настроек, которые есть только на странице форков, то
       нужно добавить их и на страницу новых карт»): the engine's stairway annexes (platforms 96-192 up with stairs and a
       pickup) on a rooms map from scratch - its own row; 0 «Нет» as on the other page. 3.58 took the other page's value
       unseen (his mg_new_38706: 4) */
    public int StairAnnexes { get; set; }
    public static readonly int[] PlateChoices = { 50, 75, 100, 150, 200 };

    public static readonly string[] StackItems =
    {
        "item_armor_body", "item_armor_combat", "item_armor_jacket", "item_health_mega", "item_quad",
        "item_invulnerability", "item_adrenaline", "item_pack",
    };

    public static readonly string[] WeaponOrder =
    {
        "weapon_shotgun", "weapon_supershotgun", "weapon_machinegun", "weapon_chaingun", "weapon_grenadelauncher",
        "weapon_rocketlauncher", "weapon_hyperblaster", "weapon_railgun", "weapon_bfg",
    };

    public static readonly string[] AllMechanics =
    {
        "clock", "halves", "key_gun_ledge", "asymmetry", "small_health", "spawn_pressure", "dead_end_stack",
        "three_approaches", "tele_mirror", "pad_pit", "lift_exposure", "ladder_item",
    };

    /// <summary>The generator's defaults by player count, as `mapgen_scratch_plan.defaults` has them (for «По умолчанию (n)»).</summary>
    /// <summary>The people's maps the generator measured (tools/mapgen_people_style.json) - offered for the style.</summary>
    public static List<string> ReferenceMaps()
    {
        try
        {
            var repo = Engine.Repo;
            var p = repo == null ? null : Path.Combine(repo, "tools", "mapgen_people_style.json");
            if (p == null || !File.Exists(p))
                return new List<string>();
            var o = JsonNode.Parse(File.ReadAllText(p));
            return (o?["maps"] as JsonObject)?.Select(kv => kv.Key).ToList() ?? new List<string>();
        }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException)
        {
            return new List<string>();
        }
    }

    public static string ClassOf(int players) => players <= 2 ? "duel" : players <= 8 ? "ffa8" : players <= 11 ? "ffa11" : "ffa16";

    public static int DefaultSpawns(int players) => ClassOf(players) switch { "duel" => 7, "ffa8" => 8, "ffa11" => 10, _ => 13 };

    public static double DefaultFloor(int players) => ClassOf(players) switch { "duel" => 2.0, "ffa8" => 3.0, "ffa11" => 3.6, _ => 4.6 };

    public static int DefaultWeapon(int players, string w)
    {
        var cls = ClassOf(players);
        return w switch
        {
            "weapon_shotgun" => cls == "duel" ? 0 : cls == "ffa16" ? 2 : 1,
            "weapon_machinegun" => cls == "duel" ? 0 : cls == "ffa16" ? 2 : 1,
            "weapon_supershotgun" => cls is "ffa11" or "ffa16" ? 2 : 1,
            "weapon_rocketlauncher" => cls is "ffa11" or "ffa16" ? 2 : 1,
            "weapon_bfg" => cls == "ffa16" ? 1 : 0,
            _ => 1,
        };
    }

    /// <summary>
    /// The mechanics «По умолчанию» as `mapgen_scratch_plan.defaults` makes them: the class's set, «halves» added when the
    /// map is two halves (its shape asked, or by default a duel's or a team game's). Brief 23: the form ticked FFA «halves»
    /// maps without «halves» while the generator added it.
    /// </summary>
    public static List<string> DefaultMechanics(int players, string shape = "", string mode = "")
    {
        var l = players <= 2
            ? new List<string> { "clock", "halves", "key_gun_ledge", "asymmetry", "small_health", "spawn_pressure" }
            : new List<string> { "clock", "small_health", "spawn_pressure" };
        var made = shape.Length > 0 ? shape : players <= 2 || mode == "tdm" ? "halves" : "arena";
        if (made == "halves" && !l.Contains("halves"))
            l.Add("halves");
        return l;
    }

    /// <summary>The parameters as `tools/mapgen_scratch.py --params` reads them: only what is not «По умолчанию».</summary>
    public string ToPython(string? clientBaseq2 = null, string? donorsDir = null)
    {
        var o = new JsonObject { ["players"] = Players, ["lang"] = Loc.Language };
        if (Spawns > 0) o["spawns"] = Spawns;
        if (SizePercent != 100) o["floor_area"] = Math.Round(DefaultFloor(Players) * SizePercent / 100.0, 2);
        if (Levels > 0) o["levels"] = Levels;
        if (SkyPercent >= 0) o["sky"] = SkyPercent / 100.0;
        if (LongLines >= 0) o["long_lines"] = LongLines;
        if (Shape.Length > 0) o["shape"] = Shape;
        if (Lifts >= 0) o["lifts"] = Lifts;
        if (Pads >= 0) o["pads"] = Pads;
        if (Teleporters >= 0) o["teleporters"] = Teleporters;
        if (WaterPercent >= 0) o["water"] = WaterPercent / 100.0;
        o["lava"] = LavaPercent / 100.0;
        o["slime"] = SlimePercent / 100.0;
        if (Weapons.Count > 0)
        {
            var w = new JsonObject();
            foreach (var k in WeaponOrder)
                w[k] = Weapons.TryGetValue(k, out var n) ? n : DefaultWeapon(Players, k);
            o["weapons"] = w;
        }
        if (Stack == "custom")
        {
            var st = new JsonObject();
            foreach (var (k, n) in StackCounts.Where(kv => kv.Value > 0))
                st[k] = n;
            o["stack"] = st;
        }
        else if (Stack.Length > 0) o["stack"] = Stack;
        if (ItemsAtHeight >= 0) o["items_at_height"] = ItemsAtHeight / 100.0;
        if (Mechanics != null) o["mechanics"] = new JsonArray(Mechanics.Select(m => (JsonNode)m!).ToArray());
        if (Windows >= 0) o["windows"] = Windows;
        if (Mode.Length > 0) o["mode"] = Mode;
        if (VerticalSpan > 0) o["vertical_span"] = VerticalSpan;
        if (CorridorPercent >= 0 || OpenPercent >= 0)
        {
            var corr = CorridorPercent >= 0 ? CorridorPercent : 40;
            var open = OpenPercent >= 0 ? OpenPercent : 10;
            o["openness"] = new JsonArray(corr / 100.0, Math.Max(0, 100 - corr - open) / 100.0, open / 100.0);
        }
        if (Stairs >= 0) o["stairs"] = Stairs;
        if (Ramps >= 0) o["ramps"] = Ramps;
        if (Ladders >= 0) o["ladders"] = Ladders;
        if (Drops >= 0) o["drops"] = Drops;
        if (Doors >= 0) o["doors"] = Doors;
        o["pits"] = Pits;
        if (Shards >= 0) o["shards"] = Shards;
        if (AmmoPerSpawn10 >= 0) o["ammo_per_spawn"] = AmmoPerSpawn10 / 10.0;
        if (HealthPerSpawn10 >= 0) o["health_per_spawn"] = HealthPerSpawn10 / 10.0;
        if (Decor.Length > 0) o["decor"] = Decor;
        if (Ships > 0) o["ships"] = Ships;
        if (PadDiscSize != 100) o["pad_disc_size"] = PadDiscSize;
        if (PadWedgeSize != 100) o["pad_wedge_size"] = PadWedgeSize;
        if (TeleFrameSize != 100) o["tele_frame_size"] = TeleFrameSize;
        if (SpawnPlateSize > 0) o["spawn_plate_size"] = SpawnPlateSize;
        if (StairAnnexes > 0) o["stair_annexes"] = StairAnnexes;
        if (WaterAboveFloor) o["water_above_floor"] = true;
        if (Sun.Length > 0) o["sun"] = Sun;
        if (Tone.Length > 0) o["tone"] = Tone;
        if (PowerupAccess.Length > 0) o["powerup_access"] = PowerupAccess;
        if (PowerupCycle) o["powerup_cycle"] = true;
        // the prizes' ways and the dives are built in rooms and halls: the page shows those rows only there
        if (PrizeAccess.Length > 0 && Shape is not ("space" or "tower")) o["prize_access"] = PrizeAccess;
        if (Underwater > 0 && Shape is not ("space" or "tower")) o["underwater"] = Underwater;
        if (WaterBody.Length > 0 && Shape is not ("space" or "tower")) o["water_body"] = WaterBody;
        // the PO 13.11: the scripted pieces - built in rooms and halls only (an island or a storey holds none)
        if (Shape is not ("space" or "tower"))
        {
            if (Trains > 0) o["trains"] = Trains;
            if (Stones > 0) o["stones"] = Stones;
            if (Traps > 0) o["traps"] = Traps;
            if (Rotators > 0) o["rotators"] = Rotators;
            if (Shutters > 0) o["shutters"] = Shutters;
            if (PickupWalls > 0) o["pickup_walls"] = PickupWalls;
            if (BentBridges > 0) o["bent_bridges"] = BentBridges;
            if (WallSteps > 0) o["wall_steps"] = WallSteps;
            if (Lasers > 0) o["lasers"] = Lasers;
            if (Pistons > 0) o["pistons"] = Pistons;
            if (Pendulums > 0) o["pendulums"] = Pendulums;
            if (Trapdoors > 0) o["trapdoors"] = Trapdoors;
            if (Geysers > 0) o["geysers"] = Geysers;
            if (TurnBridges > 0) o["turn_bridges"] = TurnBridges;
            if (Currents > 0) o["currents"] = Currents;
            if (Waves > 0) o["waves"] = Waves;
            if (TrainPath.Length > 0) o["train_path"] = TrainPath;
            if (StoneShape.Length > 0) o["stone_shape"] = StoneShape;
            if (TrapTrigger.Length > 0) o["trap_trigger"] = TrapTrigger;
            if (TrapHazard.Length > 0) o["trap_hazard"] = TrapHazard;
            if (RotatorKind.Length > 0) o["rotator_kind"] = RotatorKind;
            if (PoolLadders) o["pool_ladders"] = true;
            if (Drills > 0) o["drills"] = Drills;
            if (Cogs > 0) o["cogs"] = Cogs;
            if (Turrets > 0) o["turrets"] = Turrets;
            if (Conveyors > 0) o["conveyors"] = Conveyors;
            if (PendulumKind.Length > 0) o["pendulum_kind"] = PendulumKind;
            if (PieceMotion.Length > 0) o["piece_motion"] = PieceMotion;
            if (HammerBlast) o["hammer_blast"] = true;
            if (PieceSpeed > 0) o["piece_speed"] = PieceSpeed;
            if (PieceWait > 0) o["piece_wait"] = PieceWait;
        }

        if (ItemSpacing.Length > 0) o["item_spacing"] = ItemSpacing;
        if (ItemPractice.Length > 0) o["item_practice"] = ItemPractice;
        if (Shape == "space")
        {
            if (Islands > 0) o["islands"] = Islands;
            if (PadOnly >= 0) o["pad_only"] = PadOnly;
            if (Edges.Length > 0) o["edges"] = Edges;
            if (HeightSpread > 0) o["height_spread"] = HeightSpread;
            if (PadReach.Length > 0) o["pad_reach"] = PadReach;
            if (Bridges.Length > 0) o["bridges"] = Bridges;
        }
        if (Shape == "tower")
        {
            if (Storeys > 0) o["storeys"] = Storeys;
            if (StoreyHeight > 0) o["storey_height"] = StoreyHeight;
            if (Shafts > 0) o["shafts"] = Shafts;
            if (Perches >= 0) o["perches"] = Perches;
        }
        if (Round.Length > 0)
        {
            o["round"] = Round;
            if (RoundKinds != null)
                o["round_kinds"] = new JsonArray(RoundKinds.Select(k => (JsonNode)k!).ToArray());
        }
        var style = new JsonObject { ["source"] = Style };
        // any map (brief 21+): a base or an added .bsp by its path, a people's map of the game (its maps or its paks) by
        // its name; for «Как у карт людей» too - one of the ticked by the variant's number
        // brief 23 D1: a map added from another folder is its full path, passed as it is (never copied into the bases)
        if (StyleMaps.Count > 0)
            style["maps"] = new JsonArray(StyleMaps.Select(m =>
                (JsonNode)(Path.IsPathRooted(m) ? m
                           : donorsDir != null && File.Exists(Path.Combine(donorsDir, m + ".bsp")) ? Path.Combine(donorsDir, m + ".bsp") : m)!).ToArray());
        if (Style == "generated")
        {
            var gen = new JsonObject();
            if (GenTheme.Length > 0) gen["theme"] = GenTheme;
            if (GenColour.Length > 0) gen["colour"] = GenColour;
            if (GenWear.Length > 0) gen["wear"] = GenWear;
            if (GenScale.Length > 0) gen["scale"] = GenScale;
            if (GenRelief.Length > 0) gen["relief"] = GenRelief;
            if (GenShare.Length > 0) gen["share"] = GenShare;
            style["gen"] = gen;
        }
        o["style"] = style;
        return o.ToJsonString();
    }

    /// <summary>What a map from scratch is, in a few words for a label: «с нуля» or «с нуля, стиль q2dm1, ztn2dm3».</summary>
    public static string LabelOf(string scratchJson)
    {
        try
        {
            var o = JsonNode.Parse(scratchJson);
            var maps = (o?["style"]?["maps"] as JsonArray)?.Select(m => Path.GetFileNameWithoutExtension(m?.GetValue<string>() ?? ""))
                                                             .Where(m => m.Length > 0).ToList();
            if (maps is { Count: > 0 })
                return Loc.F("scr.label.style", string.Join(", ", maps));
            if (o?["style"]?["source"]?.GetValue<string>() == "generated")
            {
                var theme = o?["style"]?["gen"]?["theme"]?.GetValue<string>();
                return Loc.F("scr.label.gen", theme == null ? Loc.T("scr.gen.theme.auto") : Loc.T($"scr.gen.theme.{theme}"));
            }
        }
        catch (Exception e) when (e is JsonException or InvalidOperationException or FormatException)
        {
        }
        return Loc.T("scr.label");
    }

    /// <summary>«на 2 игроков, стиль: по выбранным картам» - for the run page's head.</summary>
    public static string BriefOf(string scratchJson)
    {
        try
        {
            var o = JsonNode.Parse(scratchJson);
            var players = o?["players"]?.GetValue<int>() ?? 2;
            var style = o?["style"]?["source"]?.GetValue<string>() ?? "generator";
            // «Новая карта с нуля: на 2 игроков, текстуры: Сгенерированные студией (Готика)» - the label's own «с нуля»
            // said once (the PO's run page of 05.11 read «… — с нуля, свои текстуры: Готика»)
            var maps = (o?["style"]?["maps"] as JsonArray)?.Select(m => Path.GetFileNameWithoutExtension(m?.GetValue<string>() ?? ""))
                                                             .Where(m => m.Length > 0).ToList() ?? new List<string>();
            var theme = o?["style"]?["gen"]?["theme"]?.GetValue<string>();
            var extra = new List<string>();
            if (style == "generated")
                extra.Add(theme == null ? Loc.T("scr.gen.theme.auto") : Loc.T($"scr.gen.theme.{theme}"));
            if (maps.Count > 0)
                extra.Add(string.Join(", ", maps));
            return Loc.F("scratch.brief", players, Loc.T($"scr.tex.{style}")) + (extra.Count > 0 ? $" ({string.Join("; ", extra)})" : "");
        }
        catch (Exception e) when (e is JsonException or InvalidOperationException or FormatException)
        {
            return LabelOf(scratchJson);
        }
    }

    public string Save() => JsonSerializer.Serialize(this);

    /// <summary>
    /// The parameters back from their Python form (ToPython) - what a run's request.txt keeps; the run page shows them
    /// (the PO, 05.11: «когда генерация запущена, я уже не могу вернуться и посмотреть на параметры, которые были
    /// установлены мной до запуска»). A key not given stays «По умолчанию»; `fidelity` is the request's own.
    /// </summary>
    public static ScratchParams FromPython(string json, int fidelity = 70)
    {
        var p = new ScratchParams { Fidelity = fidelity };
        JsonObject? o;
        try
        {
            o = JsonNode.Parse(json) as JsonObject;
        }
        catch (JsonException)
        {
            return p;
        }
        if (o == null)
            return p;
        int I(string k, int d) => o[k] is JsonValue v && v.TryGetValue<double>(out var x) ? (int)Math.Round(x) : d;
        int Pc(string k, int d) => o[k] is JsonValue v && v.TryGetValue<double>(out var x) ? (int)Math.Round(x * 100) : d;
        int Tenths(string k) => o[k] is JsonValue v && v.TryGetValue<double>(out var x) ? (int)Math.Round(x * 10) : -1;
        string S(JsonNode? n) => n is JsonValue v && v.TryGetValue<string>(out var s) ? s : "";
        p.Players = I("players", 2);
        p.Spawns = I("spawns", -1);
        if (o["floor_area"] is JsonValue fa && fa.TryGetValue<double>(out var area))
            p.SizePercent = (int)Math.Round(area / DefaultFloor(p.Players) * 100);
        p.Levels = I("levels", -1);
        p.SkyPercent = Pc("sky", -1);
        p.LongLines = I("long_lines", -1);
        p.Shape = S(o["shape"]);
        p.Islands = I("islands", -1);
        p.PadOnly = I("pad_only", -1);
        p.Edges = S(o["edges"]);
        p.HeightSpread = I("height_spread", -1);
        p.PadReach = S(o["pad_reach"]);
        p.Bridges = S(o["bridges"]);
        p.Storeys = I("storeys", -1);
        p.StoreyHeight = I("storey_height", -1);
        p.Shafts = I("shafts", -1);
        p.Perches = I("perches", -1);
        p.Lifts = I("lifts", -1);
        p.Pads = I("pads", -1);
        p.Teleporters = I("teleporters", -1);
        p.WaterPercent = Pc("water", -1);
        p.LavaPercent = Pc("lava", 0);
        p.SlimePercent = Pc("slime", 0);
        if (o["weapons"] is JsonObject w)
            foreach (var (k, v) in w)
                if (v is JsonValue wv && wv.TryGetValue<int>(out var n))
                    p.Weapons[k] = n;
        if (o["stack"] is JsonObject st)
        {
            p.Stack = "custom";
            foreach (var (k, v) in st)
                if (v is JsonValue sv && sv.TryGetValue<int>(out var n))
                    p.StackCounts[k] = n;
        }
        else
            p.Stack = S(o["stack"]);
        p.ItemsAtHeight = Pc("items_at_height", -1);
        if (o["mechanics"] is JsonArray m)
            p.Mechanics = m.Select(S).Where(x => x.Length > 0).ToList();
        p.Windows = I("windows", -1);
        p.Mode = S(o["mode"]);
        p.VerticalSpan = I("vertical_span", -1);
        if (o["openness"] is JsonArray op && op.Count == 3 && op[0] is JsonValue c0 && c0.TryGetValue<double>(out var corr)
            && op[2] is JsonValue c2 && c2.TryGetValue<double>(out var open))
        {
            p.CorridorPercent = (int)Math.Round(corr * 100);
            p.OpenPercent = (int)Math.Round(open * 100);
        }
        p.Stairs = I("stairs", -1);
        p.Ramps = I("ramps", -1);
        p.Ladders = I("ladders", -1);
        p.Drops = I("drops", -1);
        p.Doors = I("doors", -1);
        p.Pits = I("pits", 0);
        p.Shards = I("shards", -1);
        p.AmmoPerSpawn10 = Tenths("ammo_per_spawn");
        p.HealthPerSpawn10 = Tenths("health_per_spawn");
        p.Decor = S(o["decor"]);
        p.Ships = I("ships", -1) is var sh && sh > 0 ? sh : -1;
        p.PadDiscSize = I("pad_disc_size", 100);
        p.PadWedgeSize = I("pad_wedge_size", 100);
        p.TeleFrameSize = I("tele_frame_size", 100);
        p.SpawnPlateSize = Math.Max(0, I("spawn_plate_size", 0));
        p.StairAnnexes = Math.Clamp(I("stair_annexes", 0), 0, 10);
        p.WaterAboveFloor = o["water_above_floor"] is JsonValue wa && wa.TryGetValue<bool>(out var wab) && wab;
        p.Sun = S(o["sun"]);
        p.Tone = S(o["tone"]);
        p.PowerupAccess = S(o["powerup_access"]);
        p.PowerupCycle = o["powerup_cycle"] is JsonValue pc && pc.TryGetValue<bool>(out var pcb) && pcb;
        p.PrizeAccess = S(o["prize_access"]);
        p.Underwater = Math.Clamp(I("underwater", 0), 0, 3);
        p.WaterBody = S(o["water_body"]);
        p.Trains = Math.Clamp(I("trains", 0), 0, 3);
        p.Stones = Math.Clamp(I("stones", 0), 0, 3);
        p.Traps = Math.Clamp(I("traps", 0), 0, 2);
        p.Rotators = Math.Clamp(I("rotators", 0), 0, 3);
        p.Shutters = Math.Clamp(I("shutters", 0), 0, 2);
        p.PickupWalls = Math.Clamp(I("pickup_walls", 0), 0, 2);
        p.BentBridges = Math.Clamp(I("bent_bridges", 0), 0, 2);
        p.WallSteps = Math.Clamp(I("wall_steps", 0), 0, 3);
        p.Lasers = Math.Clamp(I("lasers", 0), 0, 2);
        p.Pistons = Math.Clamp(I("pistons", 0), 0, 2);
        p.Pendulums = Math.Clamp(I("pendulums", 0), 0, 2);
        p.Trapdoors = Math.Clamp(I("trapdoors", 0), 0, 2);
        p.Geysers = Math.Clamp(I("geysers", 0), 0, 3);
        p.TurnBridges = Math.Clamp(I("turn_bridges", 0), 0, 2);
        p.Currents = Math.Clamp(I("currents", 0), 0, 2);
        p.Waves = Math.Clamp(I("waves", 0), 0, 2);
        p.TrainPath = S(o["train_path"]);
        p.StoneShape = S(o["stone_shape"]);
        p.TrapTrigger = S(o["trap_trigger"]);
        p.TrapHazard = S(o["trap_hazard"]);
        p.RotatorKind = S(o["rotator_kind"]);
        p.PoolLadders = o["pool_ladders"] is JsonValue pl && pl.TryGetValue<bool>(out var plb) && plb;
        p.Drills = Math.Clamp(I("drills", 0), 0, 3);
        p.Cogs = Math.Clamp(I("cogs", 0), 0, 3);
        p.Turrets = Math.Clamp(I("turrets", 0), 0, 2);
        p.Conveyors = Math.Clamp(I("conveyors", 0), 0, 2);
        p.PendulumKind = S(o["pendulum_kind"]);
        p.PieceMotion = S(o["piece_motion"]) == "even" ? "even" : "";
        p.HammerBlast = o["hammer_blast"] is JsonValue hb && hb.TryGetValue<bool>(out var hbb) && hbb;
        p.PieceSpeed = I("piece_speed", 0);
        p.PieceWait = I("piece_wait", 0);

        p.ItemSpacing = S(o["item_spacing"]);
        p.ItemPractice = S(o["item_practice"]);
        p.Round = S(o["round"]);
        if (o["round_kinds"] is JsonArray rk)
            p.RoundKinds = rk.Select(S).Where(x => x.Length > 0).ToList();
        if (o["style"] is JsonObject style)
        {
            p.Style = S(style["source"]) is { Length: > 0 } src ? src : "generator";
            if (style["maps"] is JsonArray maps)
                p.StyleMaps = maps.Select(S).Where(x => x.Length > 0).Select(x => Path.GetFileNameWithoutExtension(x)).ToList();
            if (style["gen"] is JsonObject gen)
            {
                p.GenTheme = S(gen["theme"]);
                p.GenColour = S(gen["colour"]);
                p.GenWear = S(gen["wear"]);
                p.GenScale = S(gen["scale"]);
                p.GenRelief = S(gen["relief"]);
                p.GenShare = S(gen["share"]);
            }
        }
        return p;
    }

    public static ScratchParams Load(string json)
    {
        try
        {
            return JsonSerializer.Deserialize<ScratchParams>(json) ?? new ScratchParams();
        }
        catch (JsonException)
        {
            return new ScratchParams();
        }
    }

    /// <summary>One line for the run's summary: «на 2 игроков, размер 100 %, ...».</summary>
    public string Summary() => Loc.F("scratch.summary", Players,
                                     Spawns > 0 ? Spawns.ToString(CultureInfo.InvariantCulture) : Loc.T("gen.default").ToLowerInvariant(),
                                     SizePercent);
}
