/*
===========================================================================
Q2PRO-X — which logical CPUs are the fast ones.

AVFX has read the processor topology since 1.5: `GetLogicalProcessorInformationEx`
gives an EfficiencyClass per physical core, the highest class is what Intel and
Snapdragon call a P-core, and its job pool prefers those and one thread per SMT
sibling group before it doubles up.

The map generator wants the same answer for a different reason - how many
threads to give the compiler, and how many oracle workers to run - so the
detection is here rather than copied. It is the ANSWER that is shared; who acts
on it, and how, stays where it belongs. Nothing in this file knows about jobs,
cvars, the renderer or the client.

Best effort by design: a machine whose topology cannot be read is reported as
one class of equal CPUs, which is what every non-hybrid machine is anyway.
===========================================================================
*/

#pragma once

#include <stdbool.h>
#include <stdint.h>

/* No machine this ships on has more, and a fixed bound keeps every caller
   free of allocation. */
#define Q2PROX_CPU_MAX      64

typedef struct {
    int  cpu_index;             /* logical CPU number within group 0        */
    int  efficiency_class;      /* higher is faster; hybrids report 2+      */
    int  smt_sibling_group;     /* logical CPUs of one physical core share  */
} q2prox_cpu_t;

/*
 * The machine's logical CPUs, in the order the OS reported them.
 *
 * Returns how many were written. Zero means the topology could not be read,
 * and a caller that gets zero should fall back to treating every CPU as equal
 * rather than refusing to run.
 */
int Q2PROX_Cpu_Topology(q2prox_cpu_t *out, int max);

/* The highest efficiency class present: anything below it is an E-core. */
int Q2PROX_Cpu_PerformanceClass(void);

/*
 * How many logical CPUs are performance cores.
 *
 * The number to size a thread pool or a compiler's `-threads` by. At least 1
 * always, and the count of every logical CPU when the topology is unknown.
 */
int Q2PROX_Cpu_PerformanceCount(void);

/*
 * Preferred CPUs in the order a pool should take them: one per physical
 * P-core first, then their SMT siblings, then E-cores when `with_ecores`.
 *
 * CPU 0 is left out - it is where the main thread lives.
 */
int Q2PROX_Cpu_PreferredOrder(int *out, int max, bool with_ecores);

/*
 * This process's CPU time so far, user plus kernel, in milliseconds.
 *
 * Every thread's, the finished ones included, so a pool's workers are in it;
 * a child process - a compiler run through a pipe - is not. `clock()` where
 * there is no Win32. MAPGEN-1 assignment 24 D28: wall time on a loaded machine
 * is not a measurement of the code, and CPU over wall is a walk's parallel
 * yield.
 */
uint64_t Q2PROX_Cpu_ProcessMs(void);

/*
 * How many logical CPUs this process may run on: the population of its
 * affinity mask, which a launcher may have narrowed. Zero when it cannot be
 * read.
 */
int Q2PROX_Cpu_AffinityCount(void);
