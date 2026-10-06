#!/usr/bin/env python3
"""Strict package-level validation for created or updated Q2PRO-X DOCX files."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
TRUE_VALUES = {"1", "true", "on"}
EXTERNAL_FIELD = re.compile(
    r"(?:^|\s)(?:INCLUDEPICTURE|INCLUDETEXT|LINK|DDEAUTO|DDE|RD)(?:\s|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Result:
    path: Path
    errors: tuple[str, ...]
    media_count: int
    sha256: str


def _xml(data: bytes, part: str) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid XML in {part}: {exc}") from exc


def _is_true(value: str | None) -> bool:
    # In WordprocessingML, an on/off element without w:val means true.
    return value is None or value.strip().lower() in TRUE_VALUES


def validate(path: Path) -> Result:
    resolved = path.resolve()
    errors: list[str] = []
    media_count = 0
    digest = ""

    if resolved.suffix.lower() != ".docx":
        errors.append("file extension is not .docx")
    if not resolved.is_file():
        errors.append("file does not exist")
        return Result(resolved, tuple(errors), media_count, digest)

    digest = hashlib.sha256(resolved.read_bytes()).hexdigest().upper()

    try:
        with zipfile.ZipFile(resolved, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                errors.append(f"corrupt ZIP member: {bad_member}")

            names = set(archive.namelist())
            for required in ("[Content_Types].xml", "word/document.xml"):
                if required not in names:
                    errors.append(f"missing required DOCX part: {required}")

            media_count = sum(name.startswith("word/media/") for name in names)

            for name in sorted(names):
                if name.endswith(".rels"):
                    root = _xml(archive.read(name), name)
                    for relationship in root.findall(f"{{{PKG_REL_NS}}}Relationship"):
                        if relationship.attrib.get("TargetMode", "").lower() == "external":
                            target = relationship.attrib.get("Target", "")
                            errors.append(f"external relationship in {name}: {target}")

                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue

                root = _xml(archive.read(name), name)
                field_parts: list[str] = []
                for element in root.iter():
                    if element.tag == f"{{{W_NS}}}updateFields":
                        if _is_true(element.attrib.get(f"{{{W_NS}}}val")):
                            errors.append(f"automatic field update enabled in {name}")

                    linked_rel = element.attrib.get(f"{{{R_NS}}}link")
                    if linked_rel:
                        errors.append(f"linked drawing/object in {name}: {linked_rel}")

                    if element.tag == f"{{{W_NS}}}instrText" and element.text:
                        field_parts.append(element.text)
                    elif element.tag == f"{{{W_NS}}}fldSimple":
                        instruction = element.attrib.get(f"{{{W_NS}}}instr")
                        if instruction:
                            field_parts.append(instruction)

                field_code = " ".join(field_parts)
                if EXTERNAL_FIELD.search(field_code):
                    errors.append(f"external-file field code in {name}")

            app_part = "docProps/app.xml"
            if app_part in names:
                app_root = _xml(archive.read(app_part), app_part)
                links_up_to_date = next(
                    (element for element in app_root.iter() if element.tag.endswith("}LinksUpToDate")),
                    None,
                )
                if links_up_to_date is not None:
                    value = (links_up_to_date.text or "").strip().lower()
                    if value != "true":
                        errors.append("docProps/app.xml: LinksUpToDate must be true")
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        errors.append(str(exc))

    return Result(resolved, tuple(sorted(set(errors))), media_count, digest)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject Q2PRO-X DOCX files that can prompt for external-field updates."
    )
    parser.add_argument("documents", nargs="+", type=Path)
    args = parser.parse_args()

    failed = False
    for document in args.documents:
        result = validate(document)
        if result.errors:
            failed = True
            print(f"FAIL {result.path}")
            for error in result.errors:
                print(f"  - {error}")
        else:
            print(
                f"PASS {result.path} media={result.media_count} "
                f"sha256={result.sha256}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
