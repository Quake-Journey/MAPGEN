/*
===========================================================================
Q2PRO-X — which logical CPUs are the fast ones.

Lifted verbatim in behaviour from AVFX's job pool, which has read this since
1.5. Two callers now want the same answer - the pool, and the map generator
deciding how many threads to give a compiler - and one detection with two
readers is the only arrangement in which they cannot come to disagree about
what a P-core is.

The EfficiencyClass byte is read through an overlay rather than by name: it was
added in Windows 10 and older mingw headers do not declare it, while the field
offset inside PROCESSOR_RELATIONSHIP (Flags, EfficiencyClass, Reserved[20],
GroupCount, GroupMask) has been stable since it appeared.
===========================================================================
*/

#include "common/q2prox_cpu_topology.h"

#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

static q2prox_cpu_t s_cpus[Q2PROX_CPU_MAX];
static int          s_count;

/*
 * Read once.
 *
 * Two callers asking at the same time could both find the lazy flag clear and
 * both fill the table - a race that only ever showed up as a wrong count, and
 * only sometimes. The answer never changes during a run, so it is computed
 * under a once-primitive and read freely afterwards.
 */
#ifdef _WIN32
static INIT_ONCE s_once = INIT_ONCE_STATIC_INIT;
#elif defined(__STDC_NO_THREADS__)
/* No C11 threads: an atomic flag is still a publication protocol, where a
   plain bool is only a comment about one. */
static volatile int s_queried;
#else
#include <threads.h>
static once_flag s_once = ONCE_FLAG_INIT;
#endif

static void query_now(void)
{
    s_count = 0;

#ifdef _WIN32
    DWORD len = 0;
    GetLogicalProcessorInformationEx(RelationProcessorCore, NULL, &len);
    if (!len)
        return;

    SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX *buf = malloc(len);
    if (!buf)
        return;
    if (!GetLogicalProcessorInformationEx(RelationProcessorCore, buf, &len)) {
        free(buf);
        return;
    }

    int next_smt_group = 0;
    BYTE *p = (BYTE *)buf;
    BYTE *end = p + len;
    while (p < end) {
        SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX *info =
            (SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX *)p;
        if (info->Relationship == RelationProcessorCore) {
            const int eff = ((const BYTE *)&info->Processor)[1];
            for (DWORD g = 0; g < info->Processor.GroupCount; g++) {
                const KAFFINITY mask = info->Processor.GroupMask[g].Mask;
                for (int b = 0; b < 64; b++) {
                    if (!(mask & (((KAFFINITY)1) << b)))
                        continue;
                    if (s_count >= Q2PROX_CPU_MAX)
                        continue;
                    q2prox_cpu_t *c = &s_cpus[s_count++];
                    c->cpu_index = b;
                    c->efficiency_class = eff;
                    c->smt_sibling_group = next_smt_group;
                }
            }
            next_smt_group++;
        }
        p += info->Size;
    }
    free(buf);
#endif
}

#ifdef _WIN32
static BOOL CALLBACK query_once(PINIT_ONCE once, PVOID param, PVOID *context)
{
    (void)once; (void)param; (void)context;
    query_now();
    return TRUE;
}
#endif

static void query(void)
{
#ifdef _WIN32
    InitOnceExecuteOnce(&s_once, query_once, NULL, NULL);
#elif defined(__STDC_NO_THREADS__)
    /*
     * Acquire on the way in, release on the way out: a reader that sees the
     * flag set is guaranteed to see the table the writer filled, which a plain
     * bool does not promise. The dedicated server links this module, and
     * nothing in the API stops two of its threads asking at once.
     */
    if (__atomic_load_n(&s_queried, __ATOMIC_ACQUIRE))
        return;
    query_now();
    __atomic_store_n(&s_queried, 1, __ATOMIC_RELEASE);
#else
    call_once(&s_once, query_now);
#endif
}

int Q2PROX_Cpu_Topology(q2prox_cpu_t *out, int max)
{
    query();
    if (!out || max <= 0)
        return s_count;
    const int n = s_count < max ? s_count : max;
    memcpy(out, s_cpus, (size_t)n * sizeof(*out));
    return n;
}

int Q2PROX_Cpu_PerformanceClass(void)
{
    query();
    int highest = 0;
    for (int i = 0; i < s_count; i++)
        if (s_cpus[i].efficiency_class > highest)
            highest = s_cpus[i].efficiency_class;
    return highest;
}

int Q2PROX_Cpu_PerformanceCount(void)
{
    query();

    if (!s_count) {
        /* The topology could not be read. Every CPU is then as good as every
           other, which is exactly true of a non-hybrid machine. */
#ifdef _WIN32
        SYSTEM_INFO si;
        GetSystemInfo(&si);
        const int all = (int)si.dwNumberOfProcessors;
        return all > 0 ? all : 1;
#else
        return 1;
#endif
    }

    const int threshold = Q2PROX_Cpu_PerformanceClass();
    int fast = 0;
    for (int i = 0; i < s_count; i++)
        if (s_cpus[i].efficiency_class >= threshold)
            fast++;
    return fast > 0 ? fast : 1;
}

int Q2PROX_Cpu_PreferredOrder(int *out, int max, bool with_ecores)
{
    query();
    if (!out || max <= 0 || !s_count)
        return 0;

    const int threshold = Q2PROX_Cpu_PerformanceClass();
    bool used_smt[Q2PROX_CPU_MAX] = { false };
    int n = 0;

    /* One per physical P-core: a pool that filled SMT siblings first would be
       two threads on one core while another core sat idle. */
    for (int i = 0; i < s_count && n < max; i++) {
        const q2prox_cpu_t *c = &s_cpus[i];
        if (!c->cpu_index || c->efficiency_class < threshold)
            continue;
        if (c->smt_sibling_group < Q2PROX_CPU_MAX
            && used_smt[c->smt_sibling_group])
            continue;
        out[n++] = c->cpu_index;
        if (c->smt_sibling_group < Q2PROX_CPU_MAX)
            used_smt[c->smt_sibling_group] = true;
    }
    /* then their siblings */
    for (int i = 0; i < s_count && n < max; i++) {
        const q2prox_cpu_t *c = &s_cpus[i];
        if (!c->cpu_index || c->efficiency_class < threshold)
            continue;
        bool already = false;
        for (int j = 0; j < n && !already; j++)
            already = out[j] == c->cpu_index;
        if (!already)
            out[n++] = c->cpu_index;
    }
    /* and the efficiency cores last, when the caller wants them at all */
    if (with_ecores) {
        for (int i = 0; i < s_count && n < max; i++) {
            const q2prox_cpu_t *c = &s_cpus[i];
            if (!c->cpu_index || c->efficiency_class >= threshold)
                continue;
            out[n++] = c->cpu_index;
        }
    }
    return n;
}

uint64_t Q2PROX_Cpu_ProcessMs(void)
{
#ifdef _WIN32
    FILETIME created, exited, kernel, user;
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel,
                         &user))
        return 0;
    const uint64_t k = ((uint64_t)kernel.dwHighDateTime << 32)
                     | kernel.dwLowDateTime;
    const uint64_t u = ((uint64_t)user.dwHighDateTime << 32)
                     | user.dwLowDateTime;
    return (k + u) / 10000u;          /* hundreds of nanoseconds */
#else
    return (uint64_t)clock() * 1000u / (uint64_t)CLOCKS_PER_SEC;
#endif
}

int Q2PROX_Cpu_AffinityCount(void)
{
#ifdef _WIN32
    DWORD_PTR mine = 0, system = 0;
    if (!GetProcessAffinityMask(GetCurrentProcess(), &mine, &system))
        return 0;
    int n = 0;
    for (; mine; mine &= mine - 1)
        n++;
    return n;
#else
    return 0;
#endif
}
