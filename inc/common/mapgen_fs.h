/*
 * MAPGEN file or memory (ledger row 411, Fable's brief 8).
 *
 * A path that begins "mem:" is a named shared-memory SECTION this process made
 * (Windows CreateFileMapping on the paging file, `Local\q2mem_<rest>` with
 * backslashes made slashes) - the same layout the pinned compiler's patch P13
 * opens: a 32-byte header ("Q2MEM1", room, size, present) and the bytes. Any
 * other path is a file, and every call does what the code before it did.
 *
 * The sections live while this process holds them: made by MapGenFs_MakeDir for
 * a directory of a compile (its .map, .bsp, .prt, .pts and the replay's check
 * map), given back by MapGenFs_Release*. The compiler, a process of its own,
 * only opens them.
 */
#ifndef MAPGEN_FS_H
#define MAPGEN_FS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

bool MapGenFs_IsMem(const char *path);

/* The room of each section made from now on, in bytes (default 32 MB). */
void MapGenFs_SetRoom(uint64_t bytes);
uint64_t MapGenFs_Room(void);

/* The total room of the sections this process holds now, and the most it has held. */
uint64_t MapGenFs_LiveBytes(void);
uint64_t MapGenFs_PeakBytes(void);

/*
 * The bytes that went from one program to another through a pipe - this process's streams into sections, the
 * compiler's own (its portal file written and read, its point file, everything it prints). Windows counts a pipe's
 * bytes as WRITTEN, a file's the same way; what reached the disk is the count less these.
 */
void MapGenFs_NotePipe(uint64_t bytes);
uint64_t MapGenFs_PipeBytes(void);
/* What this process itself has written so far, files and pipes alike (Windows' count). */
uint64_t MapGenFs_SelfWritten(void);

/* A directory of a compile: a folder (mkdir), or its sections for `name`.map/.bsp/.prt/.pts/.replay.map. */
bool MapGenFs_MakeDir(const char *dir, const char *name);
/* Every file directly in it removed / every section of it emptied. */
void MapGenFs_EmptyDir(const char *dir);
/* The sections of a directory given back (nothing for a folder). */
void MapGenFs_ReleaseDir(const char *dir);
/* Every "<root>/try_*" directory's sections given back but `keep`'s. */
void MapGenFs_ReleaseTries(const char *root, const char *keep);

/* A whole file or section read into a new buffer (NUL-terminated past `size`); false if absent. */
bool MapGenFs_Read(const char *path, uint8_t **data, size_t *size);
/* A whole file or section written; a section must have been made. */
bool MapGenFs_Write(const char *path, const void *data, size_t size);
/* Present, and how big. */
bool MapGenFs_Exists(const char *path, uint64_t *size);
void MapGenFs_Remove(const char *path);

/*
 * A stream to write a file or a section with stdio (fputs, fprintf, fwrite):
 * on a section, a CRT pipe whose other end a thread collects into memory -
 * the bytes are exactly the ones a file opened with the same mode would hold.
 * MapGenFs_Close stores them; it must be the one to close such a stream.
 */
FILE *MapGenFs_OpenWrite(const char *path, const char *mode);
int MapGenFs_Close(FILE *f);

#endif
