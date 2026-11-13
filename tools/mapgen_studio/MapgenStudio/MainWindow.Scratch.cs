using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// Brief 19 D8: the third way to start a map - «Новая карта с нуля». No base list, no likeness, no frame: the cards of
/// what the PO named («кол-во лестниц, джампадов, лифтов, воды, лавы, кислоты, сколько точек спавна, какое оружие,
/// какие айтемы ... в каком стиле текстуры ... на какое кол-во человек рассчитана карта»), each row «По умолчанию»
/// first - the generator's choice from the player count, said in the run's record.
/// </summary>
public sealed partial class MainWindow
{
    private static readonly int[] PlayerChoices = { 2, 3, 4, 6, 8, 10, 12, 16 };
    private static readonly int[] SizeChoices = { 60, 80, 100, 125, 150, 200 };
    private static readonly int[] LiquidPercents = { 0, 2, 5, 10, 15, 20, 30 };

    /// <summary>The two ways to start, side by side at the page's head.</summary>
    private Control ModeSwitch()
    {
        var fromBase = new ToggleButton { Content = Loc.T("scratch.mode.base"), IsChecked = !S.ScratchMode, Padding = new Thickness(18, 8, 18, 8) };
        var fromNothing = new ToggleButton { Content = Loc.T("scratch.mode.new"), IsChecked = S.ScratchMode, Padding = new Thickness(18, 8, 18, 8) };
        fromBase.Tip("scratch.mode.base.tip");
        fromNothing.Tip("scratch.mode.new.tip");
        void Pick(bool scratch)
        {
            if (S.ScratchMode == scratch)
            {
                fromBase.IsChecked = !scratch;
                fromNothing.IsChecked = scratch;
                return;
            }
            S.ScratchMode = scratch;
            KeepForm();
            // a name the other way gave by itself («mg_20_42» from a base, «mg_new_42» from scratch) is not the user's -
            // the new way gives its own (the PO's picture, 04.11: «mg_1_6714» on the page of a map from scratch)
            if (_formName is { } given && System.Text.RegularExpressions.Regex.IsMatch(given, @"^mg_(new|\d+)_\d+$"))
                _formName = null;
            Rebuild();
        }
        fromBase.Click += (_, _) => Pick(false);
        fromNothing.Click += (_, _) => Pick(true);
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Children = { fromBase, fromNothing } };
        var card = Look.Group(FASymbol.Map, Look.BlueC, Loc.T("scratch.mode"), Loc.T("scratch.mode.desc"), row);
        Search.Always(card);                        // brief 35: the way to start is no parameter - always in place
        return card;
    }

    /// <summary>The cards of a map from scratch.</summary>
    private (Control people, Control shape, Control moves, Control? liquids, Control items, Control mechanics, Control style,
             Control? own, Control? pieces) ScratchCards(ScratchParams? shown = null)
    {
        // `shown`: a run's parameters on its page, to look at only - nothing of it goes into the settings
        var p = shown ?? S.Scratch;
        var viewOnly = shown != null;
        var people = new OptionGroup("scr.people", "scr.people.desc", FASymbol.People, Look.BlueC);
        var shape = new OptionGroup("scr.shape", "scr.shape.desc", FASymbol.Map, Look.TealC);
        // brief 28 (the PO 06.11: «Почему нельзя было разбить группу Размер и форма на две … плитки»): the open space's
        // and the tower's own rows a card of their own, beside «Размер и форма», only with that shape
        var own = p.Shape == "space" ? new OptionGroup("scr.own.space", "scr.own.space.desc", FASymbol.Globe, Look.VioletC)
                : p.Shape == "tower" ? new OptionGroup("scr.own.tower", "scr.own.tower.desc", FASymbol.Map, Look.AmberC)
                : null;
        var moves = new OptionGroup("scr.moves", "scr.moves.desc", FASymbol.Upload, Look.VioletC);
        var liquids = new OptionGroup("scr.liquids", "scr.liquids.desc", FASymbol.Globe, Look.BlueC);
        var items = new OptionGroup("scr.items", "scr.items.desc", FASymbol.Target, Look.RedC);
        var mech = new OptionGroup("scr.mech", "scr.mech.desc", FASymbol.Flag, Look.AmberC);
        // the PO 13.11: «архитектурного уникального для карт лоска ... постройками, которые имеют движение и/или
        // интерактивность с игроком и вносят доп опасность, но и доп интерес к их посещению»
        var pieces = new OptionGroup("scr.pieces", "scr.pieces.desc", FASymbol.Flag, Look.TealC);
        var style = new OptionGroup("scr.style", "scr.style.desc", FASymbol.Edit, Look.PinkC);
        // a choice that shows or hides rows builds the page again - never on a run's page (nothing changes there)
        void Again()
        {
            if (!viewOnly)
                Rebuild();
        }
        void Keep()
        {
            if (viewOnly)
                return;
            S.Scratch = p;
            KeepForm();
        }
        void Combo(OptionGroup g, string key, string[] items_, int index, Action<int> set)
        {
            // brief 23 D2: a value the row cannot show (a preset's, an old run's) is said to the self-test - the combo
            // would show its first choice while the run gets the value
            if (index < 0 || index >= items_.Length)
                _choiceMisses.Add($"{key} = {index}");
            var box = new ComboBox { MinWidth = 240, ItemsSource = items_, SelectedIndex = Math.Clamp(index, 0, items_.Length - 1) }.Tip($"{key}.tip");
            box.SelectionChanged += (_, _) =>
            {
                set(Math.Max(0, box.SelectedIndex));
                Keep();
            };
            g.Add(Loc.T(key), Loc.T($"{key}.tip"), box, $"{key}.tip");
        }
        string Def(string said) => $"{Loc.T("gen.default")} ({said})";
        // the mechanics' default ticks follow the shape and the mode («две половины» brings its own) - shown anew when
        // they change and the mechanics are the defaults
        void DefaultsMove(Action set)
        {
            var was = p.Mechanics == null ? string.Join(",", ScratchParams.DefaultMechanics(p.Players, p.Shape, p.Mode)) : null;
            set();
            if (was != null && was != string.Join(",", ScratchParams.DefaultMechanics(p.Players, p.Shape, p.Mode)))
            {
                Keep();
                Again();
            }
        }
        // counts with «По умолчанию» first: index 0 -> -1, index k -> values[k - 1]
        void Count(OptionGroup g, string key, int[] values, int current, string defSaid, Action<int> set)
        {
            var names = new[] { Def(defSaid) }.Concat(values.Select(v => v.ToString())).ToArray();
            Combo(g, key, names, current < 0 ? 0 : Array.IndexOf(values, current) is var at && at >= 0 ? at + 1 : -1, i => set(i == 0 ? -1 : values[i - 1]));
        }
        // who it is for
        Combo(people, "scr.players", PlayerChoices.Select(n => n == 2 ? Loc.T("scr.players.duel") : n.ToString()).ToArray(),
              Array.IndexOf(PlayerChoices, p.Players), i =>
              {
                  p.Players = PlayerChoices[i];
                  Keep();
                  Again();       // the defaults said beside each row follow the player count
              });
        var modes = new[] { "", "duel", "ffa", "tdm" };
        Combo(people, "scr.mode", new[] { Def(Loc.T(p.Players <= 2 ? "scr.mode.duel" : "scr.mode.ffa")), Loc.T("scr.mode.duel"),
                                          Loc.T("scr.mode.ffa"), Loc.T("scr.mode.tdm") },
              Array.IndexOf(modes, p.Mode), i => DefaultsMove(() => p.Mode = modes[i]));
        Count(people, "scr.spawns", Enumerable.Range(2, 23).ToArray(), p.Spawns, ScratchParams.DefaultSpawns(p.Players).ToString(), v => p.Spawns = v);
        // brief 32: a plate under every spawn - none by default, as before
        Combo(people, "scr.spawn_plate", new[] { Def(Loc.T("scr.none").ToLowerInvariant()) }.Concat(ScratchParams.PlateChoices.Select(v => $"{v} %")).ToArray(),
              p.SpawnPlateSize <= 0 ? 0 : Array.IndexOf(ScratchParams.PlateChoices, p.SpawnPlateSize) is var pi_ && pi_ >= 0 ? pi_ + 1 : -1,
              i => p.SpawnPlateSize = i == 0 ? 0 : ScratchParams.PlateChoices[i - 1]);
        // size and shape
        Combo(shape, "scr.size", SizeChoices.Select(v => v == 100 ? Def($"{ScratchParams.DefaultFloor(p.Players):0.0} {Loc.T("scr.mu2")}") : $"{v} %").ToArray(),
              Array.IndexOf(SizeChoices, p.SizePercent), i => p.SizePercent = SizeChoices[i]);
        Count(shape, "scr.levels", new[] { 2, 3, 4, 5, 6, 7 }, p.Levels, "4", v => p.Levels = v);
        Count(shape, "scr.vspan", new[] { 128, 192, 256, 384, 512, 768, 1024 }, p.VerticalSpan, "256–512", v => p.VerticalSpan = v);
        Count(shape, "scr.corr", new[] { 10, 20, 30, 40, 50, 60, 70 }, p.CorridorPercent, "40 %", v => p.CorridorPercent = v);
        Count(shape, "scr.open", new[] { 0, 5, 10, 20, 30, 40 }, p.OpenPercent, "10 %", v => p.OpenPercent = v);
        Count(shape, "scr.sky", new[] { 0, 10, 20, 30, 40, 50, 70, 100 }, p.SkyPercent, p.Style is "generator" or "generated" ? "30 %" : Loc.T("scr.bystyle").ToLowerInvariant(),
              v => p.SkyPercent = v);
        Count(shape, "scr.lines", new[] { 0, 1, 2, 3, 4, 5, 6 }, p.LongLines, p.Players <= 2 ? "2" : "4", v => p.LongLines = v);
        var shapes = new[] { "", "halves", "arena", "ring", "space", "tower" };
        Combo(shape, "scr.form", new[] { Def(Loc.T(p.Players <= 2 ? "scr.form.halves" : "scr.form.arena")), Loc.T("scr.form.halves"),
                                         Loc.T("scr.form.arena"), Loc.T("scr.form.ring"), Loc.T("scr.form.space"), Loc.T("scr.form.tower") },
              Array.IndexOf(shapes, p.Shape), i =>
              {
                  var wasOwn = p.Shape is "space" or "tower" ? p.Shape : "";
                  DefaultsMove(() => p.Shape = shapes[i]);
                  // brief 25: the space's and the tower's own rows come and go with the shape
                  if (wasOwn != (p.Shape is "space" or "tower" ? p.Shape : ""))
                  {
                      Keep();
                      Again();
                  }
              });
        if (p.Shape == "space")
        {
            Count(own!, "scr.space.islands", new[] { 6, 8, 10, 12, 16 }, p.Islands, ScratchParams.DefaultIslands(p.Players).ToString(),
                  v => p.Islands = v);
            Count(own!, "scr.space.padonly", new[] { 0, 1, 2, 3, 4, 5 }, p.PadOnly, "2", v => p.PadOnly = v);
            var edges = new[] { "", "open", "some", "railings" };
            Combo(own!, "scr.space.edges", new[] { Def(Loc.T("scr.space.edges.open").ToLowerInvariant()), Loc.T("scr.space.edges.open"),
                                                    Loc.T("scr.space.edges.some"), Loc.T("scr.space.edges.railings") },
                  Array.IndexOf(edges, p.Edges), i => p.Edges = edges[i]);
            Count(own!, "scr.space.spread", new[] { 400, 600, 800, 1000, 1300 }, p.HeightSpread, "800", v => p.HeightSpread = v);
            var reach = new[] { "", "short", "medium", "long" };
            Combo(own!, "scr.space.reach", new[] { Def(Loc.T("scr.space.reach.medium").ToLowerInvariant()), Loc.T("scr.space.reach.short"),
                                                    Loc.T("scr.space.reach.medium"), Loc.T("scr.space.reach.long") },
                  Array.IndexOf(reach, p.PadReach), i => p.PadReach = reach[i]);
            var bridges = new[] { "", "none", "some", "many" };
            Combo(own!, "scr.space.bridges", new[] { Def(Loc.T("scr.space.bridges.some").ToLowerInvariant()), Loc.T("scr.space.bridges.none"),
                                                      Loc.T("scr.space.bridges.some"), Loc.T("scr.space.bridges.many") },
                  Array.IndexOf(bridges, p.Bridges), i => p.Bridges = bridges[i]);
        }
        if (p.Shape == "tower")
        {
            // brief 25 B: whole storeys round an atrium (pro_q2t4)
            Count(own!, "scr.tower.storeys", new[] { 2, 3, 4 }, p.Storeys, "3", v => p.Storeys = v);
            Count(own!, "scr.tower.height", new[] { 160, 192, 224 }, p.StoreyHeight, "192", v => p.StoreyHeight = v);
            Count(own!, "scr.tower.shafts", new[] { 1, 2, 3 }, p.Shafts, "2", v => p.Shafts = v);
            Count(own!, "scr.tower.perches", new[] { 0, 1, 2, 3 }, p.Perches, "2", v => p.Perches = v);
        }
        // the ways between levels. 3.57 (Fable's review of 3.56; the PO's mg_new_66267 asked water and round shapes of an
        // open space and got neither): an open space builds none of the rooms' ways but its teleporters - its pads come
        // from its islands (its own card) - so the form does not offer them (mapgen_scratch_space.SPACE_FORCED)
        // a tower likewise: its storeys round an atrium, up by its pads and shafts (its own card)
        var space = p.Shape is "space" or "tower";
        if (!space)
        {
            Count(moves, "scr.stairs", new[] { 0, 2, 3, 4, 6, 8, 12, 16, 24 }, p.Stairs, Loc.T("scr.bylevels"), v => p.Stairs = v);
            Count(moves, "scr.ramps", new[] { 0, 1, 2, 3, 4, 6, 8, 12 }, p.Ramps, "0", v => p.Ramps = v);
            Count(moves, "scr.lifts", new[] { 0, 1, 2, 3, 4, 6, 8 }, p.Lifts, "2", v => p.Lifts = v);
            Count(moves, "scr.pads", new[] { 0, 1, 2, 3, 4, 6 }, p.Pads, p.Players <= 2 ? "0" : "1", v => p.Pads = v);
        }
        // brief 34 (the PO 08.11: «можно же лестницы строить, лифты, а не напихивать джампады ради джампадов»; «лифты как
        // в небоскрёбах»): a tower climbs by a flight a storey, a lift stopping on every storey and one express pad - its
        // own three rows (the values the rooms' rows have, so a shape changed keeps what it can show)
        if (p.Shape == "tower")
        {
            Count(moves, "scr.tower.stairs", new[] { 0, 1, 2, 3, 4, 6, 8, 12, 16, 24 }, p.Stairs, Loc.T("scr.tower.stairs.def"), v => p.Stairs = v);
            Count(moves, "scr.tower.lifts", new[] { 0, 1, 2, 3, 4, 6, 8 }, p.Lifts, "1", v => p.Lifts = v);
            Count(moves, "scr.tower.pads", new[] { 0, 1, 2, 3, 4, 6 }, p.Pads, "1", v => p.Pads = v);
        }
        Count(moves, "scr.teleporters", new[] { 0, 1, 2, 3, 4 }, p.Teleporters, p.Players <= 2 ? "0" : "1", v => p.Teleporters = v);
        // brief 32: how big the pads and the teleporters' frames are - «По умолчанию (100 %)» as before; an open space's and a
        // tower's pads too (theirs come from their own card)
        void Size(string key, int current, Action<int> set) =>
            Combo(moves, key, new[] { Def("100 %") }.Concat(ScratchParams.SizeChoices.Select(v => $"{v} %")).ToArray(),
                  current == 100 ? 0 : Array.IndexOf(ScratchParams.SizeChoices, current) is var at_ && at_ >= 0 ? at_ + 1 : -1,
                  i => set(i == 0 ? 100 : ScratchParams.SizeChoices[i - 1]));
        Size("scr.pad_disc_size", p.PadDiscSize, v => p.PadDiscSize = v);
        Size("scr.pad_wedge_size", p.PadWedgeSize, v => p.PadWedgeSize = v);
        Size("scr.tele_frame_size", p.TeleFrameSize, v => p.TeleFrameSize = v);
        if (!space)
        {
            Count(moves, "scr.ladders", new[] { 0, 1, 2, 3, 4, 6, 8 }, p.Ladders, "0", v => p.Ladders = v);
            // brief 33: the engine's stairway annexes - this page's own row (the other page's no longer reaches here)
            Combo(moves, "scr.stair_annexes", Enumerable.Range(0, 11).Select(n => n == 0 ? Loc.T("gen.stairways.none") : n.ToString()).ToArray(),
                  Math.Clamp(p.StairAnnexes, 0, 10), i => p.StairAnnexes = i);
            Count(moves, "scr.drops", new[] { 0, 1, 2, 3, 4, 6, 8, 12 }, p.Drops, Loc.T("scr.bylevels"), v => p.Drops = v);
            Count(moves, "scr.doors", new[] { 0, 1, 2, 3, 4, 6, 8 }, p.Doors, "0", v => p.Doors = v);
            Count(moves, "scr.windows", new[] { 0, 2, 4, 6, 8, 12 }, p.Windows, "4", v => p.Windows = v);
        }
        // liquids
        Count(liquids, "scr.water", LiquidPercents, p.WaterPercent, "5 %", v => p.WaterPercent = v);
        if (p.Shape is not ("space" or "tower"))
        {
            // the PO 12.11: deep pools as on well-known maps, pools on several floors joined by tubes, or 3.66's pits
            var bodies = ScratchParams.WaterBodies;
            Combo(liquids, "scr.waterbody", bodies.Select(v => v.Length == 0 ? Def(Loc.T("scr.waterbody.people").ToLowerInvariant())
                                                                            : Loc.T($"scr.waterbody.{v}")).ToArray(),
                  Array.IndexOf(bodies, p.WaterBody), i => p.WaterBody = bodies[i]);
        }
        Combo(liquids, "scr.lava", LiquidPercents.Select(v => v == 0 ? Loc.T("scr.none") : $"{v} %").ToArray(),
              Array.IndexOf(LiquidPercents, p.LavaPercent), i => p.LavaPercent = LiquidPercents[i]);
        Combo(liquids, "scr.slime", LiquidPercents.Select(v => v == 0 ? Loc.T("scr.none") : $"{v} %").ToArray(),
              Array.IndexOf(LiquidPercents, p.SlimePercent), i => p.SlimePercent = LiquidPercents[i]);
        Combo(liquids, "scr.pits", new[] { Loc.T("scr.none"), "1", "2", "3" }, p.Pits, i => p.Pits = i);
        // the PO, 04.11: water standing above a floor's edge «как желе» - only when allowed here, off by default
        var above = new CheckBox { IsChecked = p.WaterAboveFloor }.Tip("scr.water.above.tip");
        above.IsCheckedChanged += (_, _) =>
        {
            p.WaterAboveFloor = above.IsChecked == true;
            Keep();
        };
        liquids.Add(Loc.T("scr.water.above"), Loc.T("scr.water.above.tip"), above, "scr.water.above.tip");
        // the PO 13.11: the scripted pieces - movers, triggers, traps (rooms and halls only)
        if (p.Shape is not ("space" or "tower"))
        {
            int[] Upto(int hi) => Enumerable.Range(1, hi).ToArray();
            Count(pieces, "scr.pc.trains", Upto(3), p.Trains > 0 ? p.Trains : -1, "0", v => p.Trains = Math.Max(0, v));
            Combo(pieces, "scr.pc.train_path", ScratchParams.TrainPaths.Select(v => v.Length == 0 ? Def(Loc.T("scr.pc.mix").ToLowerInvariant())
                                                                 : Loc.T($"scr.pc.train_path.{v}")).ToArray(),
                  Array.IndexOf(ScratchParams.TrainPaths, p.TrainPath), i => p.TrainPath = ScratchParams.TrainPaths[i]);
            Count(pieces, "scr.pc.stones", Upto(3), p.Stones > 0 ? p.Stones : -1, "0", v => p.Stones = Math.Max(0, v));
            Combo(pieces, "scr.pc.stone_shape", ScratchParams.StoneShapes.Select(v => v.Length == 0 ? Def(Loc.T("scr.pc.mix").ToLowerInvariant())
                                                                 : Loc.T($"scr.pc.stone_shape.{v}")).ToArray(),
                  Array.IndexOf(ScratchParams.StoneShapes, p.StoneShape), i => p.StoneShape = ScratchParams.StoneShapes[i]);
            Count(pieces, "scr.pc.traps", Upto(2), p.Traps > 0 ? p.Traps : -1, "0", v => p.Traps = Math.Max(0, v));
            Combo(pieces, "scr.pc.trap_trigger", ScratchParams.TrapTriggers.Select(v => v.Length == 0 ? Def(Loc.T("scr.pc.mix").ToLowerInvariant())
                                                                 : Loc.T($"scr.pc.trap_trigger.{v}")).ToArray(),
                  Array.IndexOf(ScratchParams.TrapTriggers, p.TrapTrigger), i => p.TrapTrigger = ScratchParams.TrapTriggers[i]);
            Combo(pieces, "scr.pc.trap_hazard", ScratchParams.TrapHazards.Select(v => v.Length == 0 ? Def(Loc.T("scr.pc.mix").ToLowerInvariant())
                                                                 : Loc.T($"scr.pc.trap_hazard.{v}")).ToArray(),
                  Array.IndexOf(ScratchParams.TrapHazards, p.TrapHazard), i => p.TrapHazard = ScratchParams.TrapHazards[i]);
            Count(pieces, "scr.pc.rotators", Upto(3), p.Rotators > 0 ? p.Rotators : -1, "0", v => p.Rotators = Math.Max(0, v));
            Combo(pieces, "scr.pc.rotator_kind", ScratchParams.RotatorKinds.Select(v => v.Length == 0 ? Def(Loc.T("scr.pc.mix").ToLowerInvariant())
                                                                 : Loc.T($"scr.pc.rotator_kind.{v}")).ToArray(),
                  Array.IndexOf(ScratchParams.RotatorKinds, p.RotatorKind), i => p.RotatorKind = ScratchParams.RotatorKinds[i]);
            Count(pieces, "scr.pc.waves", Upto(2), p.Waves > 0 ? p.Waves : -1, "0", v => p.Waves = Math.Max(0, v));
            Count(pieces, "scr.pc.currents", Upto(2), p.Currents > 0 ? p.Currents : -1, "0", v => p.Currents = Math.Max(0, v));
            Count(pieces, "scr.pc.turn_bridges", Upto(2), p.TurnBridges > 0 ? p.TurnBridges : -1, "0", v => p.TurnBridges = Math.Max(0, v));
            Count(pieces, "scr.pc.trapdoors", Upto(2), p.Trapdoors > 0 ? p.Trapdoors : -1, "0", v => p.Trapdoors = Math.Max(0, v));
            Count(pieces, "scr.pc.geysers", Upto(3), p.Geysers > 0 ? p.Geysers : -1, "0", v => p.Geysers = Math.Max(0, v));
            Count(pieces, "scr.pc.lasers", Upto(2), p.Lasers > 0 ? p.Lasers : -1, "0", v => p.Lasers = Math.Max(0, v));
            Count(pieces, "scr.pc.pistons", Upto(2), p.Pistons > 0 ? p.Pistons : -1, "0", v => p.Pistons = Math.Max(0, v));
            Count(pieces, "scr.pc.pendulums", Upto(2), p.Pendulums > 0 ? p.Pendulums : -1, "0", v => p.Pendulums = Math.Max(0, v));
            Combo(pieces, "scr.pc.pendulum_kind", ScratchParams.PendulumKinds.Select(v => v.Length == 0 ? Def(Loc.T("scr.pc.mix").ToLowerInvariant())
                                                                 : Loc.T($"scr.pc.pendulum_kind.{v}")).ToArray(),
                  Math.Max(0, Array.IndexOf(ScratchParams.PendulumKinds, p.PendulumKind)), i => p.PendulumKind = ScratchParams.PendulumKinds[i]);
            var blast = new CheckBox { IsChecked = p.HammerBlast }.Tip("scr.pc.hammer_blast.tip");
            blast.IsCheckedChanged += (_, _) =>
            {
                p.HammerBlast = blast.IsChecked == true;
                Keep();
            };
            pieces.Add(Loc.T("scr.pc.hammer_blast"), Loc.T("scr.pc.hammer_blast.tip"), blast, "scr.pc.hammer_blast.tip");
            Count(pieces, "scr.pc.drills", Upto(3), p.Drills > 0 ? p.Drills : -1, "0", v => p.Drills = Math.Max(0, v));
            Count(pieces, "scr.pc.cogs", Upto(3), p.Cogs > 0 ? p.Cogs : -1, "0", v => p.Cogs = Math.Max(0, v));
            Count(pieces, "scr.pc.turrets", Upto(2), p.Turrets > 0 ? p.Turrets : -1, "0", v => p.Turrets = Math.Max(0, v));
            Count(pieces, "scr.pc.conveyors", Upto(2), p.Conveyors > 0 ? p.Conveyors : -1, "0", v => p.Conveyors = Math.Max(0, v));
            Count(pieces, "scr.pc.shutters", Upto(2), p.Shutters > 0 ? p.Shutters : -1, "0", v => p.Shutters = Math.Max(0, v));
            Count(pieces, "scr.pc.pickup_walls", Upto(2), p.PickupWalls > 0 ? p.PickupWalls : -1, "0", v => p.PickupWalls = Math.Max(0, v));
            Count(pieces, "scr.pc.bent_bridges", Upto(2), p.BentBridges > 0 ? p.BentBridges : -1, "0", v => p.BentBridges = Math.Max(0, v));
            Count(pieces, "scr.pc.wall_steps", Upto(3), p.WallSteps > 0 ? p.WallSteps : -1, "0", v => p.WallSteps = Math.Max(0, v));
            var ladders = new CheckBox { IsChecked = p.PoolLadders }.Tip("scr.pc.pool_ladders.tip");
            ladders.IsCheckedChanged += (_, _) =>
            {
                p.PoolLadders = ladders.IsChecked == true;
                Keep();
            };
            pieces.Add(Loc.T("scr.pc.pool_ladders"), Loc.T("scr.pc.pool_ladders.tip"), ladders, "scr.pc.pool_ladders.tip");
            Count(pieces, "scr.pc.piece_speed", ScratchParams.PieceSpeeds, p.PieceSpeed > 0 ? p.PieceSpeed : -1, "100 %", v => p.PieceSpeed = Math.Max(0, v));
            Count(pieces, "scr.pc.piece_wait", ScratchParams.PieceWaits, p.PieceWait > 0 ? p.PieceWait : -1, "100 %", v => p.PieceWait = Math.Max(0, v));
            Combo(pieces, "scr.pc.piece_motion", ScratchParams.PieceMotions.Select(v => v.Length == 0 ? Def(Loc.T("scr.pc.piece_motion.smooth").ToLowerInvariant())
                                                                 : Loc.T($"scr.pc.piece_motion.{v}")).ToArray(),
                  Math.Max(0, Array.IndexOf(ScratchParams.PieceMotions, p.PieceMotion)), i => p.PieceMotion = ScratchParams.PieceMotions[i]);
        }
        // weapons and items
        foreach (var w in ScratchParams.WeaponOrder)
        {
            var key = w;
            var def = ScratchParams.DefaultWeapon(p.Players, w);
            var names = new[] { Def(def == 0 ? Loc.T("scr.none").ToLowerInvariant() : def.ToString()), Loc.T("scr.none"), "1", "2", "3" };
            var cur = p.Weapons.TryGetValue(w, out var n) ? n + 1 : 0;
            Combo(items, $"scr.w.{w}", names, cur, i =>
            {
                if (i == 0)
                    p.Weapons.Remove(key);
                else
                    p.Weapons[key] = i - 1;
            });
        }
        /* brief 21 D6: a free-for-all's default set holds a quad (the PO, 05.11: «где там квад?») */
        var stacks = new[] { "", "ra_mh", "ra_mh_quad", "mh_adren_2ya", "2ya_adren_quad", "custom" };
        Combo(items, "scr.stack", new[] { Def(Loc.T(p.Players <= 2 ? "scr.stack.ra_mh" : "scr.stack.ra_mh_quad")), Loc.T("scr.stack.ra_mh"),
                                          Loc.T("scr.stack.ra_mh_quad"), Loc.T("scr.stack.mh_adren_2ya"),
                                          Loc.T("scr.stack.2ya_adren_quad"), Loc.T("scr.stack.custom") },
              Array.IndexOf(stacks, p.Stack), i =>
              {
                  var was = p.Stack;
                  p.Stack = stacks[i];
                  if ((was == "custom") != (p.Stack == "custom"))
                  {
                      Keep();
                      Again();          // the counts of «свой» show or go
                  }
              });
        if (p.Stack == "custom")
            foreach (var it in ScratchParams.StackItems)
            {
                var k = it;
                Combo(items, $"scr.st.{it}", new[] { Loc.T("scr.none"), "1", "2", "3" },
                      p.StackCounts.GetValueOrDefault(it), i => p.StackCounts[k] = i);
            }
        /* 3.46, the PO 05.11 («добавь опыт для новых карт с medusa_b1 - тут необычная архитектура, есть закруглённые
           части, возвышения над уровнем ниже тоже закруглённые плоские … чтобы подобное можно было выбирать и
           настраивать»): how much of the round shapes, and which */
        var rounds = new[] { "", "few", "some", "many" };
        if (p.Shape is not ("space" or "tower"))
        Combo(shape, "scr.round", new[] { Def(Loc.T("scr.none").ToLowerInvariant()), Loc.T("scr.round.few"), Loc.T("scr.round.some"),
                                          Loc.T("scr.round.many") },
              Array.IndexOf(rounds, p.Round), i =>
              {
                  var was = p.Round;
                  p.Round = rounds[i];
                  if ((was.Length > 0) != (p.Round.Length > 0))
                  {
                      Keep();
                      Again();          // which shapes - shown when some are asked
                  }
              });
        if (p.Round.Length > 0 && p.Shape is not ("space" or "tower"))
            foreach (var kind in ScratchParams.AllRoundKinds)
            {
                var k = kind;
                var onKinds = p.RoundKinds ?? ScratchParams.AllRoundKinds.ToList();
                var box = new CheckBox { IsChecked = onKinds.Contains(k) }.Tip($"scr.round.{k}.tip");
                box.IsCheckedChanged += (_, _) =>
                {
                    var now = new List<string>(p.RoundKinds ?? ScratchParams.AllRoundKinds.ToList());
                    now.Remove(k);
                    if (box.IsChecked == true)
                        now.Add(k);
                    p.RoundKinds = now.Count == ScratchParams.AllRoundKinds.Length ? null : now;
                    Keep();
                };
                shape.Add(Loc.T($"scr.round.{k}"), Loc.T($"scr.round.{k}.tip"), box, $"scr.round.{k}.tip");
            }
        // the PO, 05.11: the powerups' places - how hard to get, and the cycle in one nook
        var access = new[] { "", "easy", "medium", "hard", "mixed" };
        Combo(items, "scr.pw", new[] { Def(Loc.T("scr.pw.mixed").ToLowerInvariant()), Loc.T("scr.pw.easy"), Loc.T("scr.pw.medium"),
                                       Loc.T("scr.pw.hard"), Loc.T("scr.pw.mixed") },
              Array.IndexOf(access, p.PowerupAccess), i => p.PowerupAccess = access[i]);
        var cycle = new CheckBox { IsChecked = p.PowerupCycle }.Tip("scr.pw.cycle.tip");
        cycle.IsCheckedChanged += (_, _) =>
        {
            p.PowerupCycle = cycle.IsChecked == true;
            Keep();
        };
        items.Add(Loc.T("scr.pw.cycle"), Loc.T("scr.pw.cycle.tip"), cycle, "scr.pw.cycle.tip");
        // the PO 12.11: the items' pick-up worth - how the prizes are earned, how many under water, how far apart the
        // majors keep, whose practice (the knowledge base of people's maps)
        var prizes = ScratchParams.PrizeAccesses;
        if (p.Shape is not ("space" or "tower"))
        {
            // the prizes' ways and the dives are built in rooms and halls (an island or a storey has no floor to sink)
            Combo(items, "scr.prize", prizes.Select(v => v.Length == 0 ? Def(Loc.T("scr.prize.people").ToLowerInvariant())
                                                                        : Loc.T($"scr.prize.{v}")).ToArray(),
                  Array.IndexOf(prizes, p.PrizeAccess), i => p.PrizeAccess = prizes[i]);
            Count(items, "scr.under", new[] { 1, 2, 3 }, p.Underwater > 0 ? p.Underwater : -1, "0", v => p.Underwater = Math.Max(0, v));
        }
        var spacing = new[] { "", "people", "wide" };
        Combo(items, "scr.spacing", spacing.Select(v => v.Length == 0 ? Def(Loc.T("scr.spacing.people").ToLowerInvariant())
                                                                     : Loc.T($"scr.spacing.{v}")).ToArray(),
              Array.IndexOf(spacing, p.ItemSpacing), i => p.ItemSpacing = spacing[i]);
        var practices = ScratchParams.ItemPractices;
        Combo(items, "scr.practice", practices.Select(v => v.Length == 0 ? Def(Loc.T("scr.practice.mix"))
                                                                         : Loc.T($"scr.practice.{v}")).ToArray(),
              Array.IndexOf(practices, p.ItemPractice), i => p.ItemPractice = practices[i]);
        Count(items, "scr.shards", new[] { 0, 2, 4, 6, 8, 12 }, p.Shards, p.Players <= 2 ? "6" : "8", v => p.Shards = v);
        Count(items, "scr.ammo", new[] { 10, 15, 20, 25, 30, 40 }, p.AmmoPerSpawn10, "2,5", v => p.AmmoPerSpawn10 = v);
        Count(items, "scr.health", new[] { 5, 10, 13, 20, 30 }, p.HealthPerSpawn10, "1,3", v => p.HealthPerSpawn10 = v);
        Count(items, "scr.height", new[] { 0, 25, 50, 67, 80, 100 }, p.ItemsAtHeight, "67 %", v => p.ItemsAtHeight = v);
        // mechanics: the player count's set, ticked; any change keeps exactly what is ticked
        var on = p.Mechanics ?? ScratchParams.DefaultMechanics(p.Players, p.Shape, p.Mode);
        foreach (var m in ScratchParams.AllMechanics)
        {
            var key = m;
            var box = new CheckBox { IsChecked = on.Contains(m) }.Tip($"scr.m.{m}.tip");
            box.IsCheckedChanged += (_, _) =>
            {
                var defaults = ScratchParams.DefaultMechanics(p.Players, p.Shape, p.Mode);
                var now = new List<string>(p.Mechanics ?? defaults);
                now.Remove(key);
                if (box.IsChecked == true)
                    now.Add(key);
                // brief 23 D2: ticked back to the defaults is the defaults («По умолчанию»), as the round kinds are - a
                // preset loaded and put back by hand is that preset again
                p.Mechanics = now.ToHashSet().SetEquals(defaults) ? null : now;
                Keep();
            };
            mech.Add(Loc.T($"scr.m.{m}"), Loc.T($"scr.m.{m}.tip"), box, $"scr.m.{m}.tip");
        }
        // style
        var sources = new[] { "generator", "maps", "mixed", "generated" };
        Combo(style, "scr.tex", sources.Select(s => Loc.T($"scr.tex.{s}")).ToArray(), Array.IndexOf(sources, p.Style), i =>
        {
            var was = p.Style;
            p.Style = sources[i];
            // the Studio's own textures' parameters show or go; «Небо над головой» says its default by the style
            // (30 % for the generator's and the Studio's own, the maps' own share for the maps)
            static bool ownSky(string st) => st is "generator" or "generated";
            if ((was == "generated") != (p.Style == "generated") || ownSky(was) != ownSky(p.Style))
            {
                Keep();
                Again();
            }
        });
        if (p.Style == "generated")
        {
            /* 3.45, the PO 05.11: «пусть генерирует текстуры, когда такое разрешено в настройках, и параметры для этого
               задай» - the theme, the colour, the wear, the size of the detail, the relief, and what they dress */
            void Gen(string key, string[] values, string current, Action<string> set)
            {
                var names = values.Select((v, k) => k == 0 ? Def(Loc.T($"{key}.{values[1]}").ToLowerInvariant().Replace("—", "-"))
                                                           : Loc.T($"{key}.{v}")).ToArray();
                if (key == "scr.gen.theme" || key == "scr.gen.colour")
                    names[0] = Def(Loc.T($"{key}.auto").ToLowerInvariant());
                Combo(style, key, names, Array.IndexOf(values, current), i => set(values[i]));
            }
            Gen("scr.gen.theme", new[] { "", "tech", "gothic", "industrial", "base", "snow", "forest", "city", "planet",
                                         "fantasy", "desert", "hell" }, p.GenTheme, v => p.GenTheme = v);
            Gen("scr.gen.colour", new[] { "", "warm", "cold", "green", "rust", "grey" }, p.GenColour, v => p.GenColour = v);
            Gen("scr.gen.wear", new[] { "", "worn", "clean", "dirty" }, p.GenWear, v => p.GenWear = v);
            Gen("scr.gen.scale", new[] { "", "medium", "small", "large" }, p.GenScale, v => p.GenScale = v);
            Gen("scr.gen.relief", new[] { "", "medium", "soft", "sharp" }, p.GenRelief, v => p.GenRelief = v);
            Gen("scr.gen.share", new[] { "", "all", "detail", "walls" }, p.GenShare, v => p.GenShare = v);
        }
        /* the PO, 05.11 («карты нужно давать выбирать любые, хоть одну хоть множество, как это сделано при форках») and
           06.11 (brief 23 D1: «Добавить можно, удалить нельзя… нужно поле типа select box, в котором галочками можно
           выбрать карты с диска»): one button, its drop-down the game's maps with a tick each and a search; a .bsp from
           another folder by its path, never copied into the bases. None ticked - «Как у карт людей» takes one of the
           people's maps of the map's class */
        style.Add(Loc.T("scr.tex.maps"), Loc.T("scr.tex.maps.tip"), StyleMapsButton(p, viewOnly, Keep), "scr.tex.maps.tip");
        var decors = new[] { "", "few", "some", "many" };
        if (p.Shape != "space")
        Combo(style, "scr.decor", new[] { Def(Loc.T("scr.none").ToLowerInvariant()), Loc.T("scr.decor.few"), Loc.T("scr.decor.some.cap"), Loc.T("scr.decor.many") },
              Array.IndexOf(decors, p.Decor), i => p.Decor = decors[i]);
        var suns = new[] { "", "yes", "no" };
        Combo(style, "scr.sun", new[] { Loc.T("scr.bystyle"), Loc.T("scr.sun.yes"), Loc.T("scr.sun.no") },
              Array.IndexOf(suns, p.Sun), i => p.Sun = suns[i]);
        var tones = new[] { "", "warm", "cold" };
        Combo(style, "scr.tone", new[] { Loc.T("scr.bystyle"), Loc.T("scr.tone.warm"), Loc.T("scr.tone.cold") },
              Array.IndexOf(tones, p.Tone), i => p.Tone = tones[i]);
        // the PO 06.11: the single-player game's ships over the map (mapgen_scratch_ships), any shape
        Count(style, "scr.ships", new[] { 1, 2, 3 }, p.Ships, Loc.T("scr.none").ToLowerInvariant(), v => p.Ships = v);
        Count(style, "scr.dress", new[] { 90, 80, 70, 60, 50, 40 }, p.Fidelity == 70 ? -1 : p.Fidelity, "70", v => p.Fidelity = v < 0 ? 70 : v);
        // an open space has no liquids and no pits of its own (its void is its fall): no liquids card for it
        return (people.Card, shape.Card, moves.Card, p.Shape is "space" or "tower" ? null : liquids.Card, items.Card, mech.Card, style.Card, own?.Card,
                p.Shape is "space" or "tower" ? null : pieces.Card);
    }
}
