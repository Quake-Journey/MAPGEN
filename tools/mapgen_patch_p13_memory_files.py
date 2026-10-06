#!/usr/bin/env python3
"""Local patch P13 for the pinned compiler: memory files (ledger row 411, Fable's brief 8).

WHAT IS WRONG

The generator compiles every attempt through files: it writes the try's `.map`, the compiler's bsp stage writes the
`.bsp` and the `.prt`, vis reads both and rewrites the `.bsp`, rad reads and rewrites it again, the generator reads
it back. MEASURED 2026-10-05 (tools/mapgen_io_measure.py, the job object's own accounting, q2dm1 at 20, four builds):
29.6 MB written in 5451 operations and 241 MB read, 16 556 other file operations - a 45-build run about 330 MB in
~60 000 writes. The PO: «не столь важно сколько всего пишется на диск, важно как часто ... каждая запись на HDD это
потеря скорости генератора», and no RAM disk, no driver, no temp-folder trick.

THE PATCH

A path that begins `mem:` names a SECTION - a named shared-memory object of Windows (`Local\\q2mem_<rest>`, the rest
with its backslashes made slashes), made by the CALLER (the generator, its Python steps) and only opened here. Its
first 32 bytes are a header - "Q2MEM1", the room, the size, present - and the bytes follow. On such a path:

* `LoadFile` / `TryLoadFile` read the section (the `.map` through scriplib, the `.bsp` through LoadBSPFile);
* `WriteBSPFile` builds the file in memory - the same lumps, the same padding bytes, the header written last as it was
  - and stores it in the section;
* the `.prt` (prtfile.c, written; vis.c, read) and the `.pts` of a leak go through `QOpen` / `QClose`: a CRT pipe
  whose other end a thread of ours collects into or feeds from, so the `fprintf` / `fscanf` that were there are still
  what runs - in text mode, translating newlines exactly as the file did;
* the bsp stage's `remove` of the old `.prt` / `.pts` empties the section (`QRemove`);
* `ExpandArg` and `ExpandPath` leave a `mem:` path as it is (it is absolute).

A path that does not begin `mem:` takes the code that was there, unchanged. A section the caller did not make is an
error, not a silent file: `memory file ... was not prepared by the caller`.

    python tools/mapgen_patch_p13_memory_files.py <src> [--check | --revert]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARK = "MAPGEN-1 P13"

CMDLIB_C_CODE = r'''

/*
 * MAPGEN-1 P13: memory files.
 *
 * A path that begins "mem:" is a named shared-memory section of the caller's
 * (Local\q2mem_<rest>), never a file: a 32-byte header - "Q2MEM1", the room,
 * the size, present - then the bytes. The caller makes it; it is only opened
 * here, so a section nobody prepared is an error, not a quiet file on a disk.
 */
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#include <process.h>
#include <windows.h>

typedef struct {
    char magic[8];
    uint64_t capacity, size, present;
} q2mem_head_t;

bool MemPath(const char *path) {
    return path && !strncmp(path, "mem:", 4);
}

static q2mem_head_t *q2mem_map(const char *path, HANDLE *h) {
    char name[1200];
    char *p;
    q2mem_head_t *head;

    snprintf(name, sizeof(name), "Local\\q2mem_%s", path + 4);
    for (p = name + 6; *p; p++)
        if (*p == '\\')
            *p = '/';
    *h = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, name);
    if (!*h)
        return NULL;
    head = (q2mem_head_t *)MapViewOfFile(*h, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (!head || memcmp(head->magic, "Q2MEM1\0\0", 8)) {
        if (head)
            UnmapViewOfFile(head);
        CloseHandle(*h);
        return NULL;
    }
    return head;
}

int32_t MemLoad(const char *path, void **bufferptr) {
    HANDLE h;
    q2mem_head_t *head = q2mem_map(path, &h);
    int32_t length;
    char *buffer;

    *bufferptr = NULL;
    if (!head)
        return -1;
    if (!head->present) {
        UnmapViewOfFile(head);
        CloseHandle(h);
        return -1;
    }
    length         = (int32_t)head->size;
    buffer         = malloc(length + 1);
    buffer[length] = 0;
    memcpy(buffer, (char *)(head + 1), length);
    UnmapViewOfFile(head);
    CloseHandle(h);
    *bufferptr = buffer;
    return length;
}

void MemSave(const char *path, const void *data, size_t count) {
    HANDLE h;
    q2mem_head_t *head = q2mem_map(path, &h);

    if (!head)
        Error("memory file %s was not prepared by the caller", path);
    if (count > head->capacity)
        Error("memory file %s: %llu bytes, its room is %llu", path, (unsigned long long)count,
              (unsigned long long)head->capacity);
    head->present = 0;
    memcpy((char *)(head + 1), data, count);
    head->size    = count;
    head->present = 1;
    UnmapViewOfFile(head);
    CloseHandle(h);
}

void QRemove(const char *path) {
    HANDLE h;
    q2mem_head_t *head;

    if (!MemPath(path)) {
        remove(path);
        return;
    }
    head = q2mem_map(path, &h);
    if (!head)
        return;
    head->present = 0;
    head->size    = 0;
    UnmapViewOfFile(head);
    CloseHandle(h);
}

/* a text or binary stream on a section: a CRT pipe, its other end collected or fed by a thread */
typedef struct {
    FILE *f;
    int rd, wr;
    HANDLE thread;
    char *buf;
    size_t len, cap;
    bool writing;
    char path[1100];
} q2mem_stream_t;

static q2mem_stream_t q2mem_streams[8];

static unsigned __stdcall q2mem_collect(void *arg) {
    q2mem_stream_t *s = (q2mem_stream_t *)arg;
    char chunk[65536];
    int n;

    while ((n = _read(s->rd, chunk, sizeof(chunk))) > 0) {
        if (s->len + n > s->cap) {
            s->cap = (s->len + n) * 2;
            s->buf = realloc(s->buf, s->cap);
        }
        memcpy(s->buf + s->len, chunk, n);
        s->len += n;
    }
    _close(s->rd);
    return 0;
}

static unsigned __stdcall q2mem_feed(void *arg) {
    q2mem_stream_t *s = (q2mem_stream_t *)arg;
    size_t at = 0;

    while (at < s->len) {
        int n = _write(s->wr, s->buf + at, (unsigned)(s->len - at > 65536 ? 65536 : s->len - at));
        if (n <= 0)
            break;
        at += n;
    }
    _close(s->wr);
    return 0;
}

FILE *QOpen(const char *path, const char *mode) {
    q2mem_stream_t *s = NULL;
    bool text, writing;
    int fds[2], i;

    if (!MemPath(path))
        return fopen(path, mode);
    for (i = 0; i < 8; i++)
        if (!q2mem_streams[i].f) {
            s = &q2mem_streams[i];
            break;
        }
    if (!s)
        Error("QOpen: too many memory streams open");
    text    = strchr(mode, 'b') == NULL;
    writing = strchr(mode, 'w') != NULL;
    memset(s, 0, sizeof(*s));
    strncpy(s->path, path, sizeof(s->path) - 1);
    s->writing = writing;
    if (writing) {
        HANDLE h;
        q2mem_head_t *head = q2mem_map(path, &h);
        if (!head)
            Error("memory file %s was not prepared by the caller", path);
        UnmapViewOfFile(head);
        CloseHandle(h);
    } else {
        void *data;
        int32_t n = MemLoad(path, &data);
        if (n < 0)
            return NULL;
        s->buf = data;
        s->len = (size_t)n;
    }
    if (_pipe(fds, 1 << 16, text ? _O_TEXT : _O_BINARY))
        Error("QOpen: no pipe for %s", path);
    s->rd = fds[0];
    s->wr = fds[1];
    if (writing) {
        _setmode(s->rd, _O_BINARY); /* the collector takes the bytes the file would have held */
        s->thread = (HANDLE)_beginthreadex(NULL, 0, q2mem_collect, s, 0, NULL);
        s->f      = _fdopen(s->wr, mode);
    } else {
        _setmode(s->wr, _O_BINARY); /* the feeder gives the bytes the file held */
        s->thread = (HANDLE)_beginthreadex(NULL, 0, q2mem_feed, s, 0, NULL);
        s->f      = _fdopen(s->rd, mode);
    }
    return s->f;
}

int QClose(FILE *f) {
    int i, r;

    for (i = 0; i < 8; i++) {
        q2mem_stream_t *s = &q2mem_streams[i];
        if (s->f != f || !f)
            continue;
        r = fclose(f);
        WaitForSingleObject(s->thread, INFINITE);
        CloseHandle(s->thread);
        if (s->writing)
            MemSave(s->path, s->buf ? s->buf : "", s->len);
        free(s->buf);
        memset(s, 0, sizeof(*s));
        return r;
    }
    return fclose(f);
}
#else
bool MemPath(const char *path) {
    (void)path;
    return false;
}
int32_t MemLoad(const char *path, void **bufferptr) {
    (void)path;
    *bufferptr = NULL;
    return -1;
}
void MemSave(const char *path, const void *data, size_t count) {
    (void)data;
    (void)count;
    Error("memory file %s: no shared memory on this system", path);
}
void QRemove(const char *path) {
    remove(path);
}
FILE *QOpen(const char *path, const char *mode) {
    return fopen(path, mode);
}
int QClose(FILE *f) {
    return fclose(f);
}
#endif
'''

CMDLIB_H_CODE = '''
/* MAPGEN-1 P13: memory files - a "mem:" path is a named shared-memory section of the caller's */
bool MemPath(const char *path);
int32_t MemLoad(const char *path, void **bufferptr);
void MemSave(const char *path, const void *data, size_t count);
void QRemove(const char *path);
FILE *QOpen(const char *path, const char *mode);
int QClose(FILE *f);
'''

# (file, anchor, replacement) - each anchor must appear exactly once
EDITS = [
    ("src/cmdlib.c",
     "char *ExpandArg(const char *path) {\n    static char full[1024];\n\n    if (path[0]",
     "char *ExpandArg(const char *path) {\n    static char full[1024];\n\n"
     "    if (MemPath(path)) { /* MAPGEN-1 P13: a memory file's name is absolute */\n"
     "        strcpy(full, path);\n        return full;\n    }\n    if (path[0]"),
    ("src/cmdlib.c",
     "        Error(\"ExpandPath called without qdir set\");\n    if (path[0] == '/'",
     "        Error(\"ExpandPath called without qdir set\");\n"
     "    if (MemPath(path)) /* MAPGEN-1 P13: a memory file's name is absolute */\n        return path;\n"
     "    if (path[0] == '/'"),
    ("src/cmdlib.c",
     "    f                        = SafeOpenRead(filename);\n    length                   = Q_filelength(f);",
     "    if (MemPath(filename)) { /* MAPGEN-1 P13 */\n"
     "        length = MemLoad(filename, bufferptr);\n"
     "        if (length < 0)\n            Error(\"Error opening %s: no such memory file\", filename);\n"
     "        return length;\n    }\n"
     "    f                        = SafeOpenRead(filename);\n    length                   = Q_filelength(f);"),
    ("src/cmdlib.c",
     "    *bufferptr = NULL;\n\n    f          = fopen(filename, \"rb\");",
     "    *bufferptr = NULL;\n\n"
     "    if (MemPath(filename)) { /* MAPGEN-1 P13 */\n"
     "        length = MemLoad(filename, bufferptr);\n"
     "        if (length < 0 && print_error)\n            printf(\"  File %s failed to open\\n\", filename);\n"
     "        return length;\n    }\n\n"
     "    f          = fopen(filename, \"rb\");"),
    ("src/bsp.c",
     "    sprintf(path, \"%s.prt\", source);\n    remove(path);\n    sprintf(path, \"%s.pts\", source);\n    remove(path);",
     "    sprintf(path, \"%s.prt\", source);\n    QRemove(path); /* MAPGEN-1 P13 */\n"
     "    sprintf(path, \"%s.pts\", source);\n    QRemove(path);"),
    ("src/prtfile.c",
     "    pf = fopen(filename, \"w\");\n    if (!pf)\n        Error(\"Error opening %s\", filename);",
     "    pf = QOpen(filename, \"w\"); /* MAPGEN-1 P13 */\n    if (!pf)\n        Error(\"Error opening %s\", filename);"),
    ("src/prtfile.c",
     "    WritePortalFile_r(headnode);\n\n    fclose(pf);",
     "    WritePortalFile_r(headnode);\n\n    QClose(pf); /* MAPGEN-1 P13 */"),
    ("src/vis.c",
     "        f = fopen(name, \"r\");\n        if (!f)\n            Error(\"LoadPortals: couldn't read %s\\n\", name);",
     "        f = QOpen(name, \"r\"); /* MAPGEN-1 P13 */\n        if (!f)\n            Error(\"LoadPortals: couldn't read %s\\n\", name);"),
    ("src/vis.c",
     "    fclose(f);\n",
     "    QClose(f); /* MAPGEN-1 P13 */\n"),
    ("src/leakfile.c",
     "    linefile = fopen(filename, \"w\");",
     "    linefile = QOpen(filename, \"w\"); /* MAPGEN-1 P13 */"),
    ("src/leakfile.c",
     "    fclose(linefile);",
     "    QClose(linefile); /* MAPGEN-1 P13 */"),
    ("src/bspfile.c",
     "    lump->fileofs = LittleLong(ftell(wadfile));\n    lump->filelen = LittleLong(len);\n    SafeWrite(wadfile, data, (len + 3) & ~3);",
     "    lump->fileofs = LittleLong(bspmem_on ? (int32_t)bspmem_len : ftell(wadfile)); /* MAPGEN-1 P13 */\n"
     "    lump->filelen = LittleLong(len);\n"
     "    if (bspmem_on)\n        bspmem_put(data, (len + 3) & ~3);\n    else\n        SafeWrite(wadfile, data, (len + 3) & ~3);"),
    ("src/bspfile.c",
     "FILE *wadfile;\ndheader_t outheader;\n",
     "FILE *wadfile;\ndheader_t outheader;\n\n"
     "/* MAPGEN-1 P13: a .bsp on a mem: path is built here - the same lumps and padding - and stored at the end */\n"
     "static bool bspmem_on;\nstatic char *bspmem;\nstatic size_t bspmem_len, bspmem_cap;\n\n"
     "static void bspmem_put(const void *data, size_t count) {\n"
     "    if (bspmem_len + count > bspmem_cap) {\n"
     "        bspmem_cap = (bspmem_len + count) * 2;\n"
     "        bspmem     = realloc(bspmem, bspmem_cap);\n    }\n"
     "    memcpy(bspmem + bspmem_len, data, count);\n    bspmem_len += count;\n}\n"),
    ("src/bspfile.c",
     "    wadfile         = SafeOpenWrite(filename);\n    SafeWrite(wadfile, header, sizeof(dheader_t)); // overwritten later",
     "    bspmem_on       = MemPath(filename); /* MAPGEN-1 P13 */\n"
     "    bspmem_len      = 0;\n"
     "    wadfile         = bspmem_on ? NULL : SafeOpenWrite(filename);\n"
     "    if (bspmem_on)\n        bspmem_put(header, sizeof(dheader_t)); // overwritten later\n"
     "    else\n        SafeWrite(wadfile, header, sizeof(dheader_t)); // overwritten later"),
    ("src/bspfile.c",
     "    fseek(wadfile, 0, SEEK_SET);\n    SafeWrite(wadfile, header, sizeof(dheader_t));\n    fclose(wadfile);\n}",
     "    if (bspmem_on) { /* MAPGEN-1 P13 */\n"
     "        memcpy(bspmem, header, sizeof(dheader_t));\n"
     "        MemSave(filename, bspmem, bspmem_len);\n"
     "        bspmem_on = false;\n        return;\n    }\n"
     "    fseek(wadfile, 0, SEEK_SET);\n    SafeWrite(wadfile, header, sizeof(dheader_t));\n    fclose(wadfile);\n}"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="the q2tools source directory")
    ap.add_argument("--check", action="store_true", help="report whether the patch is applied, change nothing")
    ap.add_argument("--revert", action="store_true", help="put the source back, for a controlled RED")
    a = ap.parse_args()
    root = Path(a.src)
    files = {f for f, _, _ in EDITS} | {"src/cmdlib.h"}
    text = {}
    for f in files:
        p = root / f
        if not p.is_file():
            print(f"not found: {p}")
            return 2
        text[f] = p.read_text(encoding="utf-8", errors="surrogateescape")
    applied = (CMDLIB_C_CODE in text["src/cmdlib.c"] and CMDLIB_H_CODE in text["src/cmdlib.h"]
               and all(new in text[f] for f, _, new in EDITS))
    if a.check:
        print("P13 applied" if applied else "P13 NOT applied")
        return 0 if applied else 1
    if a.revert:
        if not applied:
            print("P13 is not applied; nothing to revert")
            return 0
        for f, old, new in reversed(EDITS):
            text[f] = text[f].replace(new, old, 1)
        text["src/cmdlib.c"] = text["src/cmdlib.c"].replace(CMDLIB_C_CODE, "", 1)
        text["src/cmdlib.h"] = text["src/cmdlib.h"].replace(CMDLIB_H_CODE, "", 1)
        for f in files:
            (root / f).write_text(text[f], encoding="utf-8", errors="surrogateescape")
        print("P13 reverted")
        return 0
    if applied:
        print("P13 is already applied; nothing to do")
        return 0
    for f, old, new in EDITS:
        if text[f].count(old) != 1:
            print(f"{f}: the anchor does not appear exactly once ({text[f].count(old)}); refusing to guess:\n{old[:80]}")
            return 1
    for f, old, new in EDITS:
        text[f] = text[f].replace(old, new, 1)
    text["src/cmdlib.c"] = text["src/cmdlib.c"].rstrip("\n") + "\n" + CMDLIB_C_CODE
    hdr = text["src/cmdlib.h"]
    at = hdr.rfind("#endif")
    if at < 0:
        print("src/cmdlib.h: no closing #endif; refusing to guess")
        return 1
    text["src/cmdlib.h"] = hdr[:at] + CMDLIB_H_CODE + "\n" + hdr[at:]
    for f in files:
        (root / f).write_text(text[f], encoding="utf-8", errors="surrogateescape")
    print("P13 applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
