/*
 * Can a player see out of this map? Asked of the map alone.
 *
 * Every other oracle here is DONOR-RELATIVE: it takes the map a fork came from
 * and asks whether each point the donor drew is still drawn. That is exactly
 * right for a fidelity-100 fork, where nothing is meant to change, and it says
 * nothing usable about a map at fidelity 75 - where walls are supposed to have
 * moved, so "the donor's wall is not here" is the operator working.
 *
 * This asks the only question that does not need a donor: from somewhere a
 * player can stand, looking in some direction, does the eye reach ANY drawn
 * surface? A sealed map has one in every direction - a wall, a floor, a sky.
 * A ray that reaches the edge of the world without meeting one is the strip of
 * nothing in the middle of a wall that the PO photographed.
 *
 *     mapgen_open_view <map.bsp> [--step N] [--rays N] [--verbose]
 *
 * It deliberately does not consult the collision hull. The hull carries bevel
 * planes that no face is drawn on, which is what defeated the attempt before
 * this one - it reported three thousand holes in an untouched q2dm1 - and the
 * question here is about what is DRAWN.
 *
 * --- what it is calibrated to -------------------------------------------
 *
 * Four causes of false alarm were found and each is worth knowing:
 *
 *   the sky is drawn even though its faces carry NODRAW - q2dm1's sky is
 *   flags 0x85 - so excluding nodraw made every upward ray in an outdoor map
 *   report a hole;
 *   pockets of air sealed in the rock have no drawn walls because nobody can
 *   ever be in them, so the standing places are flooded from the map's spawns;
 *   the west edge of q2dm1 is closed by a detail PLAYERCLIP volume rather than
 *   by walls, and a flood that treats clip as air walks out of the map;
 *   a sample taken hard against a wall sits ON its plane, and every ray into
 *   that wall then meets its face at zero distance, which reads as nothing at
 *   all. A player is thirty-two units across, so his eye is never within
 *   sixteen of a wall - and the probe steps out in fours, because one probe at
 *   sixteen jumps clean over a wall sixteen thick.
 *
 * After all four, MEASURED at 128 units and 42 rays: q2dm1, q2dm2, q2dm3 and
 * q2dm8 report ZERO blind rays out of 34,398, and so do all five maps handed
 * to the PO on 2026-09-07. check_mapgen_open_view.py holds them there.
 *
 * Exit 0 when every ray meets a surface, 1 when one does not.
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"

#define MAX_POLY   64
#define MAX_SPOTS  4096
#define CLUSTER    128.0

/* Surfaces the compiler emits but never draws. SKY is drawn: seeing the sky is
   a map working, and seeing it through a crease is what the donor-relative
   oracle catches. */
/*
 * What stops a player.
 *
 * Not CONTENTS_SOLID alone. q2dm1's western edge is closed by a detail
 * PLAYERCLIP volume rather than by walls, and a flood that treats clip as air
 * walks out into it and then reports - correctly, but uselessly - that there
 * are no surfaces out there. 128 of q2dm1's 157 blind rays were that one
 * place.
 */
#define CONTENTS_SOLID_BIT      0x00000001
#define CONTENTS_PLAYERCLIP_BIT 0x00010000
#define STOPS_A_PLAYER (CONTENTS_SOLID_BIT | CONTENTS_PLAYERCLIP_BIT)

#define SURF_SKY_BIT    0x0004
#define SURF_NODRAW_BIT 0x0080
#define SURF_HINT_BIT   0x0100
#define SURF_SKIP_BIT   0x0200

typedef struct {
    double p[MAX_POLY][3];
    int    n;
    double normal[3];
    double dist;
    double mins[3], maxs[3];
} poly_t;

typedef struct {
    double   mins[3], maxs[3];
    uint32_t count;
} spot_t;

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) != MAPGEN_BSP_OK)
        bsp = NULL;
    free(raw);
    return bsp;
}

static bool face_poly(const mapgen_bsp_t *b, uint32_t i, poly_t *out)
{
    const mapgen_bsp_face_t *face = MapGenBsp_Face(b, i);
    if (face->numedges < 3 || face->numedges > MAX_POLY)
        return false;
    const mapgen_bsp_texinfo_t *ti =
        MapGenBsp_TexInfo(b, (uint32_t)face->texinfo);
    /*
     * Sky is DRAWN, whatever its nodraw bit says.
     *
     * q2dm1's sky wears flags 0x85 - nodraw, sky and light together - because
     * the compiler builds no lightmap for it. The engine draws it all the
     * same, and it is what a player sees when he looks up. Dropping it made
     * every upward ray in an outdoor map report a hole, which is 45 of them on
     * an untouched q2dm1 and the reason this is written down here.
     */
    const uint32_t flags = ti ? ti->flags : 0;
    if (flags & (SURF_HINT_BIT | SURF_SKIP_BIT))
        return false;
    if ((flags & SURF_NODRAW_BIT) && !(flags & SURF_SKY_BIT))
        return false;

    const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(b, face->planenum);
    const double s = face->side ? -1.0 : 1.0;
    for (int a = 0; a < 3; a++)
        out->normal[a] = pl->normal[a] * s;
    out->dist = pl->dist * s;
    out->n = face->numedges;
    for (int a = 0; a < 3; a++) {
        out->mins[a] = 1e30;
        out->maxs[a] = -1e30;
    }
    for (int32_t e = 0; e < face->numedges; e++) {
        const int32_t se = MapGenBsp_SurfEdge(b, (uint32_t)(face->firstedge + e));
        const mapgen_bsp_edge_t *ed =
            MapGenBsp_Edge(b, (uint32_t)(se < 0 ? -se : se));
        const mapgen_bsp_vertex_t *v =
            MapGenBsp_Vertex(b, se < 0 ? ed->v[1] : ed->v[0]);
        for (int a = 0; a < 3; a++) {
            out->p[e][a] = v->point[a];
            if (out->p[e][a] < out->mins[a]) out->mins[a] = out->p[e][a];
            if (out->p[e][a] > out->maxs[a]) out->maxs[a] = out->p[e][a];
        }
    }
    return true;
}

/* Does the ray meet this polygon, and how far along? */
static bool hits(const poly_t *q, const double from[3], const double dir[3],
                 double *out_t)
{
    double nd = 0.0, np = 0.0;
    for (int a = 0; a < 3; a++) {
        nd += q->normal[a] * dir[a];
        np += q->normal[a] * from[a];
    }
    if (fabs(nd) < 1e-9)
        return false;
    const double t = (q->dist - np) / nd;
    if (t <= 1.0)
        return false;

    double at[3];
    for (int a = 0; a < 3; a++) {
        at[a] = from[a] + dir[a] * t;
        if (at[a] < q->mins[a] - 0.5 || at[a] > q->maxs[a] + 0.5)
            return false;
    }

    /* Inside the polygon, measured on the two axes it is widest across. */
    int u = 0, v = 1;
    {
        int minor = 0;
        for (int a = 1; a < 3; a++)
            if (fabs(q->normal[a]) > fabs(q->normal[minor]))
                minor = a;
        u = (minor + 1) % 3;
        v = (minor + 2) % 3;
    }
    bool in = false;
    for (int e = 0, j = q->n - 1; e < q->n; j = e++) {
        const double *A = q->p[e], *B = q->p[j];
        if ((A[v] > at[v]) != (B[v] > at[v])
            && at[u] < (B[u] - A[u]) * (at[v] - A[v]) / (B[v] - A[v]) + A[u])
            in = !in;
    }
    if (!in) {
        /*
         * Half a unit outside is still hitting it.
         *
         * Two faces that meet at a corner leave nothing between them, but a
         * ray aimed at the corner can be judged a hair outside BOTH of them
         * and fly on into nothing. That is arithmetic, not a hole, and it is
         * what the last of q2dm1's blind rays were: eighteen of twenty-nine
         * from one spot, every one of them nearly parallel to a wall it did
         * hit when aimed squarely.
         */
        bool near = false;
        for (int e = 0, j = q->n - 1; e < q->n && !near; j = e++) {
            const double *A = q->p[e], *B = q->p[j];
            const double eu = A[u] - B[u], ev = A[v] - B[v];
            const double len2 = eu * eu + ev * ev;
            double s = len2 > 0 ? ((at[u] - B[u]) * eu + (at[v] - B[v]) * ev)
                                  / len2 : 0.0;
            s = s < 0 ? 0 : (s > 1 ? 1 : s);
            const double du = at[u] - (B[u] + eu * s);
            const double dv = at[v] - (B[v] + ev * s);
            near = du * du + dv * dv <= 0.25;
        }
        if (!near)
            return false;
    }
    *out_t = t;
    return true;
}

/*
 * The air a player can actually reach, flooded from the map's own spawns.
 *
 * A Quake map has pockets of air sealed in its rock that no player ever sees,
 * and the compiler draws their walls or not as it pleases. Asking about them
 * is asking about somewhere nobody is: MEASURED, they are the whole of what
 * this reported on untouched donors once the sky was counted - 42 rays on
 * q2dm1, every one of them from a pocket near the map's edge.
 */
typedef struct {
    int32_t  size[3];
    double   origin[3];
    double   step;
    uint8_t *air;
    uint8_t *seen;
} flood_t;

static int64_t cell_of(const flood_t *g, const int32_t c[3])
{
    for (int a = 0; a < 3; a++)
        if (c[a] < 0 || c[a] >= g->size[a])
            return -1;
    return (int64_t)c[0] + (int64_t)c[1] * g->size[0]
         + (int64_t)c[2] * g->size[0] * g->size[1];
}

static bool reachable(const flood_t *g, const double p[3])
{
    int32_t c[3];
    for (int a = 0; a < 3; a++)
        c[a] = (int32_t)floor((p[a] - g->origin[a]) / g->step);
    const int64_t at = cell_of(g, c);
    return at >= 0 && g->seen[at];
}

static uint32_t spawns_of(const mapgen_bsp_t *bsp, double (*out)[3],
                          uint32_t max)
{
    uint32_t n = 0;
    const char *ents = MapGenBsp_Entities(bsp, NULL);
    if (!ents)
        return 0;
    const char *p = ents;
    while (n < max && (p = strchr(p, '{'))) {
        const char *end = strchr(p, '}');
        if (!end)
            break;
        const char *cls = strstr(p, "info_player_");
        const char *org = strstr(p, "\"origin\"");
        double o[3] = { 0, 0, 0 };
        bool have = false;
        if (org && org < end) {
            const char *q = strchr(org + 8, '"');
            if (q && sscanf(q + 1, "%lf %lf %lf", &o[0], &o[1], &o[2]) == 3)
                have = true;
        }
        if (cls && cls < end && have) {
            memcpy(out[n], o, sizeof(o));
            n++;
        }
        p = end + 1;
    }
    return n;
}

/* Fill `g` with the air, then mark what a spawn can walk to. */
static bool flood(const mapgen_bsp_t *bsp, const mapgen_bsp_model_t *world,
                  double step, flood_t *g)
{
    memset(g, 0, sizeof(*g));
    g->step = step;
    for (int a = 0; a < 3; a++) {
        g->origin[a] = world->mins[a];
        g->size[a] = (int32_t)((world->maxs[a] - world->mins[a]) / step) + 2;
    }
    const int64_t cells = (int64_t)g->size[0] * g->size[1] * g->size[2];
    g->air = calloc((size_t)cells, 1);
    g->seen = calloc((size_t)cells, 1);
    int32_t *queue = calloc((size_t)cells * 3, sizeof(*queue));
    if (!g->air || !g->seen || !queue) {
        free(queue);
        return false;
    }
    for (int32_t z = 0; z < g->size[2]; z++)
      for (int32_t y = 0; y < g->size[1]; y++)
        for (int32_t x = 0; x < g->size[0]; x++) {
            const int32_t c[3] = { x, y, z };
            const float p[3] = {
                (float)(g->origin[0] + (x + 0.5) * step),
                (float)(g->origin[1] + (y + 0.5) * step),
                (float)(g->origin[2] + (z + 0.5) * step),
            };
            if (!(MapGenBsp_PointContents(bsp, p) & STOPS_A_PLAYER))
                g->air[cell_of(g, c)] = 1;
        }

    double (*starts)[3] = calloc(256, sizeof(*starts));
    const uint32_t num = spawns_of(bsp, starts, 256);
    int64_t head = 0, tail = 0;
    for (uint32_t s = 0; s < num; s++) {
        int32_t c[3];
        for (int a = 0; a < 3; a++)
            c[a] = (int32_t)floor((starts[s][a] - g->origin[a]) / step);
        const int64_t at = cell_of(g, c);
        if (at < 0 || !g->air[at] || g->seen[at])
            continue;
        g->seen[at] = 1;
        for (int a = 0; a < 3; a++)
            queue[tail * 3 + a] = c[a];
        tail++;
    }
    free(starts);
    static const int STEP[6][3] = {
        { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 },
        { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 },
    };
    while (head < tail) {
        const int32_t c[3] = { queue[head * 3], queue[head * 3 + 1],
                               queue[head * 3 + 2] };
        head++;
        for (int d = 0; d < 6; d++) {
            const int32_t n[3] = { c[0] + STEP[d][0], c[1] + STEP[d][1],
                                   c[2] + STEP[d][2] };
            const int64_t at = cell_of(g, n);
            if (at < 0 || !g->air[at] || g->seen[at])
                continue;
            g->seen[at] = 1;
            for (int a = 0; a < 3; a++)
                queue[tail * 3 + a] = n[a];
            tail++;
        }
    }
    free(queue);
    return true;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [--step N] [--rays N]"
                        " [--verbose]\n", argv[0]);
        return 2;
    }
    double step = 128.0;
    int rays = 66;
    bool verbose = false;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--step") && i + 1 < argc)
            step = strtod(argv[++i], NULL);
        else if (!strcmp(argv[i], "--rays") && i + 1 < argc)
            rays = (int)strtol(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--verbose"))
            verbose = true;
    }

    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }

    const uint32_t nf = MapGenBsp_NumFaces(bsp);
    poly_t *faces = calloc(nf ? nf : 1, sizeof(*faces));
    uint32_t count = 0;
    for (uint32_t i = 0; i < nf; i++)
        if (face_poly(bsp, i, &faces[count]))
            count++;

    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (!world || !count) {
        fprintf(stderr, "no world model or no drawn faces\n");
        return 2;
    }

    /*
     * Where a player can be: air with solid under it, at eye height.
     *
     * Not every air cell - a player is not a fly - and the standing spots are
     * where he would actually be when he noticed. The step is coarse on
     * purpose: this is a sweep for a hole big enough to see, and a hole big
     * enough to see is bigger than the gap between two standing spots.
     */
    flood_t reach;
    if (!flood(bsp, world, 32.0, &reach)) {
        fprintf(stderr, "out of memory flooding the air\n");
        return 2;
    }

    spot_t *spots = calloc(MAX_SPOTS, sizeof(*spots));
    uint32_t num_spots = 0;
    uint64_t looked = 0, blind = 0, places = 0;

    /*
     * Every floor in the column, not every point on a lattice.
     *
     * Sampling z on the same coarse step as x and y finds a floor only when
     * one happens to be there: q2dm8 came out with FOUR standing places in the
     * whole map. So each column is walked from the bottom and a place is taken
     * wherever solid turns to air, which is what a floor is.
     */
    for (double y = world->mins[1] + step * 0.5; y < world->maxs[1]; y += step)
      for (double x = world->mins[0] + step * 0.5; x < world->maxs[0];
           x += step) {
        bool was_solid = true;
        for (double z = world->mins[2]; z < world->maxs[2] - 64.0; z += 16.0) {
            const float probe[3] = { (float)x, (float)y, (float)z };
            const bool solid = (MapGenBsp_PointContents(bsp, probe) & STOPS_A_PLAYER) != 0;
            const bool floor_here = was_solid && !solid;
            was_solid = solid;
            if (!floor_here)
                continue;
            /* Standing on it, with the head clear of the ceiling. */
            const float head[3] = { (float)x, (float)y, (float)(z + 48.0) };
            if (MapGenBsp_PointContents(bsp, head) & STOPS_A_PLAYER)
                continue;
            /*
             * And a player's width clear of the walls.
             *
             * A sample taken hard against a wall sits ON its plane, and every
             * ray into that wall meets the face at zero distance - which reads
             * as "nothing there" and is nothing of the kind. MEASURED: that is
             * every one of q2dm1's last 29 blind rays, from a spot at x=1472
             * against a face whose plane IS x=1472. A player is thirty-two
             * units across, so his eye is never within sixteen of a wall, and
             * a sample that is has no business standing in for him.
             */
            /*
             * The player's whole box, not four probes down the axes.
             *
             * An inside corner where two walls meet leaves the axes clear -
             * along either wall it is air - while the DIAGONAL is solid, and a
             * thirty-two unit box centred there is half inside the rock. The
             * invented F0 map put its only six blind rays at exactly such a
             * corner. Every four units out, because one probe at sixteen steps
             * clean over a wall sixteen thick.
             */
            bool boxed_in = false;
            static const int WAY[8][2] = {
                { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 },
                { 1, 1 }, { 1, -1 }, { -1, 1 }, { -1, -1 },
            };
            for (int h = 0; h < 2 && !boxed_in; h++)
              for (int w = 0; w < 8 && !boxed_in; w++)
                for (int r = 4; r <= 16 && !boxed_in; r += 4) {
                    const float side[3] = {
                        (float)(x + WAY[w][0] * r),
                        (float)(y + WAY[w][1] * r),
                        (float)(z + (h ? 40.0 : 24.0)),
                    };
                    boxed_in = (MapGenBsp_PointContents(bsp, side)
                                & STOPS_A_PLAYER) != 0;
                }
            if (boxed_in)
                continue;
            const double at_here[3] = { x, y, z + 8.0 };
            if (!reachable(&reach, at_here))
                continue;                  /* a pocket nobody is ever in */
            places++;

            const double eye[3] = { x, y, z + 40.0 };
            for (int r = 0; r < rays; r++) {
                /* An even spread over the sphere, by the golden angle - no
                   clustering at the poles, and no table to carry. */
                const double k = (r + 0.5) / rays;
                const double phi = acos(1.0 - 2.0 * k);
                const double theta = 3.883222077450933 * r;
                const double dir[3] = { sin(phi) * cos(theta),
                                        sin(phi) * sin(theta), cos(phi) };
                looked++;

                double best = 1e30;
                for (uint32_t c = 0; c < count; c++) {
                    double t;
                    if (hits(&faces[c], eye, dir, &t) && t < best)
                        best = t;
                }
                if (best < 1e29)
                    continue;

                blind++;
                bool merged = false;
                for (uint32_t s = 0; s < num_spots && !merged; s++) {
                    bool near = true;
                    for (int a = 0; a < 3 && near; a++)
                        if (eye[a] < spots[s].mins[a] - CLUSTER
                            || eye[a] > spots[s].maxs[a] + CLUSTER)
                            near = false;
                    if (!near)
                        continue;
                    for (int a = 0; a < 3; a++) {
                        if (eye[a] < spots[s].mins[a]) spots[s].mins[a] = eye[a];
                        if (eye[a] > spots[s].maxs[a]) spots[s].maxs[a] = eye[a];
                    }
                    spots[s].count++;
                    merged = true;
                }
                if (!merged && num_spots < MAX_SPOTS) {
                    for (int a = 0; a < 3; a++)
                        spots[num_spots].mins[a] = spots[num_spots].maxs[a]
                                                 = eye[a];
                    spots[num_spots].count = 1;
                    num_spots++;
                }
                if (verbose && blind <= 8)
                    printf("  blind at %.0f %.0f %.0f looking %.2f %.2f %.2f\n",
                           eye[0], eye[1], eye[2], dir[0], dir[1], dir[2]);
            }
        }
      }

    for (uint32_t i = 1; i < num_spots; i++) {
        const spot_t key = spots[i];
        uint32_t j = i;
        while (j && spots[j - 1].count < key.count) {
            spots[j] = spots[j - 1];
            j--;
        }
        spots[j] = key;
    }

    printf("%llu standing places every %.0f units, %llu rays each,"
           " %llu that meet no drawn surface, in %u places\n",
           (unsigned long long)places, step, (unsigned long long)(rays),
           (unsigned long long)blind, num_spots);
    for (uint32_t i = 0; i < num_spots && i < 12; i++)
        printf("  %6u rays   %7.0f %7.0f %7.0f .. %7.0f %7.0f %7.0f\n",
               spots[i].count, spots[i].mins[0], spots[i].mins[1],
               spots[i].mins[2], spots[i].maxs[0], spots[i].maxs[1],
               spots[i].maxs[2]);
    if (num_spots > 12)
        printf("  ... and %u more\n", num_spots - 12);

    (void)looked;
    free(reach.air);
    free(reach.seen);
    free(spots);
    free(faces);
    MapGenBsp_Free(bsp);
    return blind ? 1 : 0;
}
