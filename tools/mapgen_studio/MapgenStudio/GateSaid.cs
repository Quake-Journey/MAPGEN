using System.Globalization;
using System.Text.RegularExpressions;

namespace MapgenStudio;

/// <summary>
/// Brief 29 D3 (brief 27 D2, the part 3.54 left: «lit: … floor at 255 2.0%, median 77, top tenth 82» in English under a
/// failed row of the PO's space map): what a failed check measured, in words, both languages - from the check's own
/// text after « -- ». Every pattern here is one a check of the PO's library wrote (his 43 gates files, 06.11; the
/// self-test reads each from a real line of them). A text no pattern knows is shown as the check wrote it - never silence.
/// </summary>
public static class GateSaid
{
    /// <summary>The 3.54 words (the text as the check wrote it, the bands only in words), for the self-test's RED.</summary>
    internal static bool Off;

    private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    private static Match M(string text, string pattern) => Regex.Match(text, pattern);

    /// <summary>A number as the check gave it, its long tails cut (0.05000000000000002 → 0.05).</summary>
    internal static string N(string v) => double.TryParse(v, NumberStyles.Float, Inv, out var d)
        ? Math.Round(d, Math.Abs(d) >= 100 ? 0 : 2).ToString(Inv) : v;

    /// <summary>An item the check names short («armor_combat», «railgun») in the description's words.</summary>
    private static string ItemWords(string shortName)
    {
        var ru = Loc.Language == "ru";
        foreach (var prefix in new[] { "", "item_", "weapon_" })
            if (Describe.PickupName(prefix + shortName, ru) is { Length: > 0 } w && w != prefix + shortName)
                return w;
        return shortName;
    }

    private static string Sec(string v) =>
        double.TryParse(v, NumberStyles.Float, Inv, out var d) ? StageArt.Seconds((float)d) : v;

    public static string Words(string what, string said)
    {
        what = Loc.WithoutAfterRuin(what).Trim();
        said = said.Trim();
        // brief 27: the 3.52 space and tower measure that was not made on the delivered map
        if (said == "not measured" && (what.StartsWith("space:") || what.StartsWith("tower:")))
            return Loc.T("lib.gates.notmeasured");
        // brief 27: a band of people's maps, «value (band lo..hi)»
        var band = M(said, @"^(-?[\d.]+)\s*\(band\s*(-?[\d.]*)\.\.(-?[\d.]*)\)");
        if (band.Success)
        {
            // a band with one end (spawn_to_stack_s «7.43 (band ..6.0)»: 3.55 said «у карт людей ….6») - «не больше 6»
            var (lo, hi) = (band.Groups[2].Value, band.Groups[3].Value);
            if (lo.Length == 0 && hi.Length > 0)
                return Loc.F("lib.gates.said.band.max", N(band.Groups[1].Value), N(hi));
            if (hi.Length == 0 && lo.Length > 0)
                return Loc.F("lib.gates.said.band.min", N(band.Groups[1].Value), N(lo));
            return Loc.F("lib.gates.said.band", N(band.Groups[1].Value), lo.Length > 0 ? N(lo) : "…", hi.Length > 0 ? N(hi) : "…");
        }
        if (Off)
            return said;
        // brief 34: «pad 5 (band ..2)» - which like things and how many stand together
        var rep = M(said, @"^([a-z]+) (\d+) \(band \.\.(\d+)\)$");
        if (rep.Success && Loc.Has($"lib.gates.said.kind.{rep.Groups[1].Value}"))
            return Loc.F("lib.gates.said.repetition", Loc.T($"lib.gates.said.kind.{rep.Groups[1].Value}"), rep.Groups[2].Value);
        return Known(what, said) ?? said;
    }

    private static string? Known(string what, string said)
    {
        var key = Loc.GateKey(what);
        Match m;
        // a check that gives its verdict and no numbers (the gates' own selftest summary line)
        if ((m = M(said, @"^SUMMARY \d+ cases? asserted, \d+ failures?")).Success)
            return Loc.T("lib.gates.said.summary");
        // a generation's records gone (the checks of an old map read its run's ledger)
        if (said.StartsWith("no fidelity and seed in "))
            return Loc.T("lib.gates.said.norecords");
        switch (key)
        {
            // the PO 12.11: the items' pick-up worth - which items, how far, the rule; which prizes are walked to
            case "gate.majors apart":
            {
                var pairs = Regex.Matches(said, @"([a-z_]+)/([a-z_]+) (\d+) u ([\d.]+|None) s \(rule (\d+) u ([\d.]+) s\)");
                if (pairs.Count == 0)
                    break;
                var more = M(said, @"and (\d+) more$");
                return string.Join("; ", pairs.Select(p => Loc.F("lib.gates.said.majors", ItemWords(p.Groups[1].Value),
                                                                 ItemWords(p.Groups[2].Value), p.Groups[3].Value, Sec(p.Groups[4].Value),
                                                                 p.Groups[5].Value, Sec(p.Groups[6].Value))))
                       + (more.Success ? Loc.F("lib.gates.said.majors.more", more.Groups[1].Value) : "");
            }
            case "gate.prizes earned":
                if (said.StartsWith("walked to: "))
                    return Loc.F("lib.gates.said.walked", string.Join(", ", said["walked to: ".Length..].Split("; ")
                                                                                 .Select(x => ItemWords(x.Split(' ')[0]))));
                break;
            case "gate.under water":
                if ((m = M(said, @"^(\d+): (.*)$")).Success)
                    return m.Groups[2].Value == "none" ? Loc.T("lib.gates.said.swum.none")
                        : Loc.F("lib.gates.said.swum", string.Join(", ", m.Groups[2].Value.Split(", ").Select(ItemWords)));
                break;
            // brief 21+: where each powerup (and a prize put in a nook) lies, as the access asked - in words (his
            // mg_new_56432 of 12.11: «armor_body hard; weapon_railgun medium (jump in) - one unlit» in English)
            case "gate.powerups":
            {
                var unlit = said.EndsWith(" - one unlit");
                var body = unlit ? said[..^" - one unlit".Length] : said;
                var notHad = M(body, @" \(not had: (.*)\)$");
                if (notHad.Success)
                    body = body[..notHad.Index];
                var parts = new List<string>();
                foreach (var one in body.Split("; "))
                {
                    var sp = one.IndexOf(' ');
                    if (sp <= 0 || !Loc.Has($"lib.gates.said.site.{one[(sp + 1)..]}"))
                        return null;
                    parts.Add($"{ItemWords(one[..sp])} — {Loc.T($"lib.gates.said.site.{one[(sp + 1)..]}")}");
                }
                return string.Join("; ", parts)
                       + (notHad.Success ? Loc.F("lib.gates.said.site.nothad", notHad.Groups[1].Value) : "")
                       + (unlit ? Loc.T("lib.gates.said.site.unlit") : "");
            }
            case "gate.mechanic «clock»":
                if ((m = M(said, @"^heights (-?\d+)/(-?\d+), exits (\d+)/(\d+)( \(nook\))?$")).Success)
                    return Loc.F("lib.gates.said.clock", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value)
                           + (m.Groups[5].Success ? Loc.T("lib.gates.said.clock.nook") : "");
                break;
            // the PO 12.11: the water as well-known maps build it
            case "gate.deep pool":
                if ((m = M(said, @"^deepest (\d+) \(from (\d+)\), its widest pool (\d+) cells of 64 \(from (\d+); q2dm1 55\)$")).Success)
                    return Loc.F("lib.gates.said.deeppool", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value);
                break;
            case "gate.tube under water":
                if ((m = M(said, @"^the longest (\d+) u \(from (\d+); q2dm1 368\)$")).Success)
                    return Loc.F("lib.gates.said.tube", m.Groups[1].Value, m.Groups[2].Value);
                break;
            // the PO 12.11 («приплыл сюда, а там пусто»): what the game frees at spawn, a spawn in a lift's column
            case "gate.pickups.spawn":
                if ((m = M(said, @"^(-?\d+) lost, (-?\d+) blocked(?:: (.*))?$")).Success)
                {
                    var each = new List<string>();
                    if (m.Groups[3].Success)
                        foreach (var one in m.Groups[3].Value.Split("; "))
                        {
                            var w = M(one, @"^([a-z_]+) at \(([-\d, ]+)\)");
                            if (w.Success)
                                each.Add(Loc.F("lib.gates.said.lost.one",
                                               w.Groups[1].Value.StartsWith("info_player") ? Loc.T("lib.gates.said.lost.spawn") : ItemWords(w.Groups[1].Value),
                                               w.Groups[2].Value.Replace(",", "")));
                        }
                    return Loc.F("lib.gates.said.lost", m.Groups[1].Value, m.Groups[2].Value) + (each.Count > 0 ? ": " + string.Join("; ", each) : "");
                }
                break;
            case "gate.water worth":
                if ((m = M(said, @"^(\d+) of (\d+) with none: (.*)$")).Success)
                    return Loc.F("lib.gates.said.worth.empty", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value);
                if ((m = M(said, @"^\d+: (.*)$")).Success)
                    return Loc.F("lib.gates.said.worth", string.Join(", ", m.Groups[1].Value.Split(", ")
                        .Select(g => string.Join(" и ", g.Split('/').Select(ItemWords)))));
                break;
            case "gate.water levels":
                if ((m = M(said, @"^(\d+) levels: (.*)$")).Success)
                    return Loc.F("lib.gates.said.waterlevels", m.Groups[1].Value, m.Groups[2].Value);
                break;
            case "gate.lit":
                if ((m = M(said, @"^floor at 255 ([\d.]+)%, median (\d+), top tenth (\d+); walls at 255 ([\d.]+)%")).Success)
                    return Loc.F("lib.gates.said.lit", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value);
                break;
            case "gate.traps-engine":
                if ((m = M(said, @"^(\d+) place\(s\)(?:, (\d+) of them inside the dead end asked)?")).Success)
                    return Loc.F("lib.gates.said.traps.places", m.Groups[1].Value)
                           + (m.Groups[2].Success ? Loc.F("lib.gates.said.traps.deadend", m.Groups[2].Value) : "");
                break;
            case "gate.traps":
                if ((m = M(said, @"^(\d+) points of 32 u(?:, (\d+) of them inside the dead end asked)?")).Success)
                    return Loc.F("lib.gates.said.traps.points", m.Groups[1].Value)
                           + (m.Groups[2].Success ? Loc.F("lib.gates.said.traps.deadend", m.Groups[2].Value) : "");
                break;
            case "gate.starts":
                if ((m = M(said, @"^(\d+) starts, (\d+) not standing free(?:: (.*))?$")).Success)
                {
                    var each = m.Groups[3].Success
                        ? m.Groups[3].Value.Split("; ").Select(StartWords).Where(x => x.Length > 0).ToList()
                        : new List<string>();
                    return Loc.F("lib.gates.said.starts", m.Groups[1].Value, m.Groups[2].Value)
                           + (each.Count > 0 ? ": " + string.Join("; ", each) : "");
                }
                break;
            case "gate.pickups.chaingun":
                if (said == "none")
                    return Loc.T("lib.gates.said.nochaingun");
                break;
            case "gate.glass":
                if ((m = M(said, @"^(\d+) shot, (\d+) on a plate \(\d+ func_button\), (\d+) other moving panes; (\d+) fixed glass faces in the world, the donor (\d+)")).Success)
                    return Loc.F("lib.gates.said.glass", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value,
                                 m.Groups[5].Value);
                break;
            case "gate.light":
                if ((m = M(said, @"^shared faces sides ([\d.]+), floors ([\d.]+), ceilings ([\d.]+) \(0\.8\.\.1\.25\); (\d+) dug rooms against their doors")).Success)
                    return Loc.F("lib.gates.said.light", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value);
                break;
            case "gate.water":
                if ((m = M(said, @"^face\s+\d+\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")).Success)
                    return Loc.F("lib.gates.said.vertical", m.Groups[1].Value, $"{m.Groups[2].Value} {m.Groups[3].Value} {m.Groups[4].Value}");
                break;
            // the look of a map from scratch (check_mapgen_new_map, brief 20/21): the PO's mg_new_66267 of 06.11 failed
            // «colour» and «round shapes» in English on a Russian page
            case "gate.colour":
                if ((m = M(said, @"^(\d+)% coloured \(people's ([\d.]+)\.\.([\d.]+) %")).Success)
                    return Loc.F("lib.gates.said.colour", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value);
                if (said.StartsWith("not measured: "))
                    return Loc.F("lib.gates.said.notmeasured.why", said["not measured: ".Length..]);
                break;
            case "gate.texture brightness":
                if ((m = M(said, @"^mean (\d+) \(people's ([\d.]+)\.\.([\d.]+)")).Success)
                    return Loc.F("lib.gates.said.texlum", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value);
                break;
            case "gate.on screen":
                if ((m = M(said, @"^median (\d+), top tenth (\d+) \(people's ([\d.]+)\.\.([\d.]+), ([\d.]+)\.\.([\d.]+)\)")).Success)
                    return Loc.F("lib.gates.said.screen", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value,
                                 m.Groups[5].Value, m.Groups[6].Value);
                break;
            case "gate.one texture":
                if ((m = M(said, @"^the largest (\d+)%, (\d+) textures")).Success)
                    return Loc.F("lib.gates.said.onetex", m.Groups[1].Value, m.Groups[2].Value);
                break;
            case "gate.light colour":
                if ((m = M(said, @"^saturation ([\d.]+) \(people's ([\d.]+)\.\.([\d.]+)\)")).Success)
                    return Loc.F("lib.gates.said.lightsat", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value);
                break;
            case "gate.textures":
                if ((m = M(said, @"^(\d+) textures over 0\.5 % of the surface \(people's (\d+)\.\.(\d+)\)")).Success)
                    return Loc.F("lib.gates.said.textures", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value);
                break;
            case "gate.round shapes":
                if ((m = M(said, @"^corners (\d+), apses (\d+), podiums (\d+) \(([^:)]*):[^)]*\)(; not made: ([^-]*) - the reason in the record)?")).Success)
                    return Loc.F("lib.gates.said.round", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value)
                           + (m.Groups[5].Success ? Loc.T("lib.gates.said.round.notmade") : "");
                break;
            // 3.57: the rows still English on the PO's library (the self-test's «the library in Russian», 07.11)
            case "gate.mechanic «adrenaline tucked»":
                if ((m = M(said, @"^height (-?\d+), nearest major ([\d.]+) s")).Success)
                    return Loc.F("lib.gates.said.adren", m.Groups[1].Value, m.Groups[2].Value);
                break;
            case "gate.mechanic «key gun on a ledge»":
                if ((m = M(said, @"^(-?\d+) over the floor around, an armour ([\d.]+) s away")).Success)
                    return Loc.F("lib.gates.said.ledge", m.Groups[1].Value, m.Groups[2].Value);
                // 3.66 (the PO 12.11): its way, the nearest armour - none asked by it any more
                if ((m = M(said, @"^(-?\d+) over the floor around(?:, its way: ([a-z]+))?, the nearest armour ([\d.]+|None) s away")).Success)
                    return Loc.F("lib.gates.said.ledge2", m.Groups[1].Value,
                                 m.Groups[2].Success && Loc.Has($"lib.gates.said.way.{m.Groups[2].Value}") ? Loc.T($"lib.gates.said.way.{m.Groups[2].Value}") : "",
                                 Sec(m.Groups[3].Value));
                break;
            case "gate.nothing hanging":
                // 3.60: every piece in words - «hangs from the ceiling» and «in the air» too (the PO's mg_new_594 on a
                // Russian page: «hangs», «from»)
                if ((m = M(said, @"^(\d+): (.+)$")).Success)
                {
                    var words = new List<string>();
                    foreach (var piece in Regex.Split(m.Groups[2].Value,
                                                      @", (?=(?:stands out of a wall|hangs from the ceiling|in the air) at )"))
                    {
                        var pm = M(piece, @"^(stands out of a wall|hangs from the ceiling|in the air) at (-?\d+ -?\d+ -?\d+)$");
                        if (!pm.Success)
                        {
                            words.Clear();
                            break;
                        }
                        words.Add(Loc.F(pm.Groups[1].Value switch
                        {
                            "stands out of a wall" => "lib.gates.said.hanging.wall",
                            "hangs from the ceiling" => "lib.gates.said.hanging.ceiling",
                            _ => "lib.gates.said.hanging.air",
                        }, pm.Groups[2].Value));
                    }
                    if (words.Count > 0)
                        return Loc.F("lib.gates.said.hanging.n", m.Groups[1].Value) + ": " + string.Join("; ", words);
                }
                break;
            case "gate.plain rooms":
                if ((m = M(said, @"^(\d+) halls or rooms with nothing but walls and doorways")).Success)
                    return Loc.F("lib.gates.said.plain", m.Groups[1].Value);
                break;
            case "gate.digwalls":
                if ((m = M(said, @"^(\d+) digs: (\d+) points open high(?: \([^)]*\))?; (\d+) points standing in the old air")).Success)
                    return Loc.F("lib.gates.said.digwalls", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value);
                break;
            case "gate.static":
                return string.Join("; ", said.Split("; ").Select(StaticPart));
            case "gate.clips":
                if ((m = M(said, @"^(\d+) found")).Success)
                    return Loc.F("lib.gates.said.clips", m.Groups[1].Value);
                break;
            case "gate.sky":
                if ((m = M(said, @"^(\d+) digs, (\d+) viewers under the sky, (\d+) points of new space, (\d+) seen through it")).Success)
                    return Loc.F("lib.gates.said.sky", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value);
                break;
            case "gate.stair":
                if ((m = M(said, @"^(\d+) eyes, (\d+) pairs LOST in plain sight")).Success)
                    return Loc.F("lib.gates.said.stair", m.Groups[1].Value, m.Groups[2].Value);
                break;
            case "gate.long sight lines over 1000 u":
                if ((m = M(said, @"^(\d+) \(people's: (\d+) at most\)")).Success)
                    return Loc.F("lib.gates.said.lines", m.Groups[1].Value, m.Groups[2].Value);
                break;
            // 3.60: his tower mg_new_18619 failed these with English words on a Russian page (the self-test, 08.11)
            case "gate.mechanic «dead-end stack»":
                if ((m = M(said, @"^\[([\d, ]*)\]$")).Success)
                    return Loc.F("lib.gates.said.deadend", m.Groups[1].Value);
                break;
            case "gate.pads apart":
                if (said == "no two on one floor")
                    return Loc.T("lib.gates.said.nopadpairs");
                break;
            // brief 35: «disc exit 64 (band 256..)» - which two stand nearest, and how near
            case "gate.movers and spawns apart":
                if ((m = M(said, @"^(disc|exit|pad|spawn) (disc|exit|pad|spawn) (\d+) \(band (\d+)\.\.\)$")).Success)
                    return Loc.F("lib.gates.said.movers", Loc.T($"lib.gates.said.mark.{m.Groups[1].Value}"),
                                 Loc.T($"lib.gates.said.mark.{m.Groups[2].Value}"), m.Groups[3].Value, m.Groups[4].Value);
                break;
            // brief 36: «3 of 7 doors (band ..0)» - how many doors have a face in a wall's plane
            case "gate.door faces":
                if ((m = M(said, @"^(\d+) of (\d+) doors \(band \.\.0\)$")).Success)
                    return Loc.F("lib.gates.said.doorfaces", m.Groups[1].Value, m.Groups[2].Value);
                break;
            case "gate.not a copy, item graph":
                if ((m = M(said, @"^([\d.]+) s from (\S+)$")).Success)
                    return Loc.F("lib.gates.said.copygraph", m.Groups[1].Value, m.Groups[2].Value);
                break;
            case "gate.not a copy, routes":
                if ((m = M(said, @"^([\d.]+) with (\S+)")).Success)
                    return Loc.F("lib.gates.said.copyroutes", m.Groups[1].Value, m.Groups[2].Value);
                break;
            case "gate.rooms over rooms":
                if ((m = M(said, @"^([\d.]+)% of the floor over or under another \(people's ([\d.]+)\.\.([\d.]+) %, median ([\d.]+) %\); rooms over rooms (\d+) of (\d+)")).Success)
                    return Loc.F("lib.gates.said.overrooms", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value, m.Groups[4].Value,
                                 m.Groups[5].Value, m.Groups[6].Value);
                break;
        }
        // the generator's own building on a base: «N halls / annexes / storeys in the plan, K on accepted digs, B built»
        if ((m = M(said, @"^(\d+) (?:halls|annexes|storeys) in the plan, (\d+) (on accepted digs|asked), (\d+) built(?:, (\d+) worth the walk)?")).Success)
            return Loc.F(m.Groups[3].Value == "asked" ? "lib.gates.said.plan.asked" : "lib.gates.said.plan", m.Groups[1].Value,
                         m.Groups[2].Value, m.Groups[4].Value)
                   + (m.Groups[5].Success ? Loc.F("lib.gates.said.plan.worth", m.Groups[5].Value) : "");
        if ((m = M(said, @"^(\d+) stairways in the plan, (\d+) accepted, (\d+) built")).Success)
            return Loc.F("lib.gates.said.stairways", m.Groups[1].Value, m.Groups[2].Value, m.Groups[3].Value);
        // what the parameters asked against what came out: «lava asked: 5% of the floor …» -- «2.2%»
        if (Asked(what, said) is { } asked)
            return asked;
        // a bare measure with its unit (the mechanics: seconds, «times as long»)
        if ((m = M(said, @"^(-?[\d.]+) s$")).Success)
            return Loc.F("lib.gates.said.seconds", m.Groups[1].Value);
        if ((m = M(said, @"^(-?[\d.]+)x$")).Success)
            return Loc.F("lib.gates.said.times", m.Groups[1].Value);
        // 3.60: «none» as a row's whole measure (a mechanic «lift as exposure» with no major item only a lift reaches)
        if (said == "none")
            return Loc.T("lib.gates.said.none");
        return null;
    }

    /// <summary>One part of «static» (its parts joined by «; »): a pane, a dig's mouth, the base's own.</summary>
    private static string StaticPart(string part)
    {
        Match m;
        if ((m = M(part, @"^pane coplanar with the world: \S+ \w+ at (\[[^\]]*\])")).Success)
            return Loc.F("lib.gates.said.static.coplanar", m.Groups[1].Value);
        if ((m = M(part, @"^pane in rock: \S+ \w+ at (\[[^\]]*\])")).Success)
            return Loc.F("lib.gates.said.static.inrock", m.Groups[1].Value);
        if ((m = M(part, @"^dig closed at an end: .*?no way in beside its lower end (-?\d+ -?\d+ -?\d+)")).Success)
            return Loc.F("lib.gates.said.static.closed", m.Groups[1].Value);
        if ((m = M(part, @"^the donor's own, there too: (\d+)")).Success)
            return Loc.F("lib.gates.said.static.donor", m.Groups[1].Value);
        return part;
    }

    /// <summary>One start of «starts»: «1182 15 705 over no floor» and the like.</summary>
    private static string StartWords(string one)
    {
        var m = M(one.Trim(), @"^(-?\d+ -?\d+ -?\d+) (buried|over no floor|cannot move)$");
        if (!m.Success)
            return one.Trim();
        return Loc.F(m.Groups[2].Value switch
        {
            "buried" => "lib.gates.said.start.buried",
            "over no floor" => "lib.gates.said.start.nofloor",
            _ => "lib.gates.said.start.stuck",
        }, m.Groups[1].Value);
    }

    /// <summary>The «asked» rows: the asked value from the row's name, the got one from its measure.</summary>
    private static string? Asked(string what, string said)
    {
        if (!what.Contains(" asked"))
            return null;
        var got = M(said, @"^(-?[\d.]+%?)");
        if (!got.Success)
            return null;
        string? asked = null;
        Match m;
        if ((m = M(what, @"asked: none")).Success)
            asked = Loc.T("lib.gates.said.none");
        else if ((m = M(what, @"asked: (?:over )?(\d+(?:\.\d+)?%)")).Success)
            asked = m.Groups[1].Value;
        else if ((m = M(what, @"(\d+(?:\.\d+)?%?) asked")).Success)
            asked = m.Groups[1].Value;
        if (asked == null)
            return null;
        var tol = M(what, @"\(\+-(\d+)( points)?\)");
        if (tol.Success)
            asked += $" (±{tol.Groups[1].Value})";
        var allowed = M(said, @"\(allowed ([\d.]+\.\.[\d.]+)\)");
        return Loc.F("lib.gates.said.asked", asked, got.Groups[1].Value)
               + (allowed.Success ? Loc.F("lib.gates.said.allowed", allowed.Groups[1].Value) : "");
    }
}
