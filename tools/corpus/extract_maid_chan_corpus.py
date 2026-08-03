#!/usr/bin/env python3
"""Extract Maid-chan conversations and supporting contexts from EPUB books.

This tool intentionally uses only the Python standard library.  It produces:

* maid_chan_fewshot.jsonl       -- agent-ready user/assistant examples
* maid_chan_conversations.jsonl -- dialogue-shaped few-shot candidates
* maid_chan_contexts.jsonl      -- every explicit Maid-chan mention with context
* maid_chan_manifest.json       -- inputs, output counts, and extraction settings

The extractor is deliberately conservative: it only labels Maid-chan turns when
the text itself, adjacent narration, a sign-off, or alternating chat structure
supports that attribution.  Uncertain turns remain labelled ``unknown``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence
from xml.etree import ElementTree


EPUB_DOCUMENT_SUFFIXES = (".xhtml", ".html", ".htm")
MAID_NAME_RE = re.compile(r"女[仆僕][酱醬]|女[仆僕](?!装|裝)")
MAID_SELF_RE = re.compile(
    r"(?:由)?女[仆僕](?:[酱醬])?我|"
    r"女[仆僕](?:[酱醬])?(?:敬上|上|报道|報道)|"
    r"以上[，,、 ]*女[仆僕](?:[酱醬])?"
)
MESSAGE_RE = re.compile(r"^\s*(?:—{1,2}|–{1,2}|-{2,}|─{1,2})\s*(.+?)\s*$")
QUOTED_RE = re.compile(r"^\s*[「『“\"](.+?)[」』”\"]\s*$")
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}


class ParagraphHTMLParser(HTMLParser):
    """Convert permissive HTML/XHTML into readable paragraph-like lines."""

    def __init__(self) -> None:
        """Initialize parser state for collected visible text fragments."""
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """Record block boundaries and ignore non-text payload elements."""
        tag = tag.lower()
        if tag in {"script", "style", "svg"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Record closing block boundaries and leave ignored elements."""
        tag = tag.lower()
        if tag in {"script", "style", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Collect visible text data outside ignored elements."""
        if self._ignored_depth == 0:
            self._parts.append(data)

    def paragraphs(self) -> list[str]:
        """Return whitespace-normalized non-empty paragraph lines."""
        text = html.unescape("".join(self._parts)).replace("\u3000", " ")
        paragraphs = []
        for line in text.splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            if clean:
                paragraphs.append(clean)
        return paragraphs


@dataclass(frozen=True)
class Document:
    """One readable content document extracted from an EPUB archive."""

    path: str
    paragraphs: tuple[str, ...]
    title: str | None


def stable_id(*parts: object) -> str:
    """Create a stable short content ID from identifying source fields."""
    raw = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def local_name(tag: str) -> str:
    """Return an XML tag name without its namespace prefix."""
    return tag.rsplit("}", 1)[-1]


def decode_document(raw: bytes) -> str:
    """Decode common Chinese EPUB encodings, preferring declared encodings."""
    head = raw[:300].decode("ascii", errors="ignore")
    match = re.search(r"encoding=[\"']([A-Za-z0-9._-]+)", head, re.I)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8-sig", "utf-8", "gb18030", "big5"])
    for encoding in dict.fromkeys(encodings):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def document_order(archive: zipfile.ZipFile) -> list[str]:
    """Return content documents in EPUB spine order, with a safe fallback."""
    names = archive.namelist()
    fallback = [name for name in names if name.lower().endswith(EPUB_DOCUMENT_SUFFIXES)]
    try:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(
            element.attrib["full-path"]
            for element in container.iter()
            if local_name(element.tag) == "rootfile"
        )
        opf = ElementTree.fromstring(archive.read(rootfile))
        manifest = {
            element.attrib["id"]: element.attrib["href"]
            for element in opf.iter()
            if local_name(element.tag) == "item"
            and element.attrib.get("id")
            and element.attrib.get("href")
        }
        base = posixpath.dirname(rootfile)
        ordered = []
        for element in opf.iter():
            if local_name(element.tag) != "itemref":
                continue
            href = manifest.get(element.attrib.get("idref", ""))
            if not href:
                continue
            path = posixpath.normpath(posixpath.join(base, href.split("#", 1)[0]))
            if path.lower().endswith(EPUB_DOCUMENT_SUFFIXES) and path in names:
                ordered.append(path)
        ordered.extend(path for path in fallback if path not in ordered)
        return ordered
    except (KeyError, StopIteration, ElementTree.ParseError):
        return fallback


def extract_title(markup: str, paragraphs: Sequence[str]) -> str | None:
    """Extract a document title from markup or a likely leading paragraph."""
    match = re.search(r"<title\b[^>]*>(.*?)</title>", markup, re.I | re.S)
    if match:
        title = re.sub(r"<[^>]+>", "", match.group(1))
        title = re.sub(r"\s+", " ", html.unescape(title)).strip()
        if title:
            return title
    for paragraph in paragraphs[:3]:
        if 1 < len(paragraph) <= 80:
            return paragraph
    return None


def read_epub(path: Path) -> list[Document]:
    """Read ordered paragraph documents from one EPUB file."""
    documents = []
    with zipfile.ZipFile(path) as archive:
        for name in document_order(archive):
            parser = ParagraphHTMLParser()
            markup = decode_document(archive.read(name))
            try:
                parser.feed(markup)
                paragraphs = tuple(parser.paragraphs())
            except Exception as exc:  # HTMLParser can encounter malformed declarations.
                print(f"warning: skipped malformed document {path.name}:{name}: {exc}", file=sys.stderr)
                continue
            if paragraphs:
                documents.append(
                    Document(
                        path=name,
                        paragraphs=paragraphs,
                        title=extract_title(markup, paragraphs),
                    )
                )
    return documents


def message_text(paragraph: str) -> str | None:
    """Return chat-message text when a paragraph uses message punctuation."""
    match = MESSAGE_RE.match(paragraph)
    return match.group(1).strip() if match else None


def is_maid_narration(text: str) -> bool:
    """Return whether narration appears to attribute communication to Maid-chan."""
    if not MAID_NAME_RE.search(text):
        return False
    return bool(
        re.search(
            r"(?:女[仆僕][酱醬].{0,12}(?:信息|消息|邮件|郵件|联络|聯絡|传话|傳話|"
            r"回复|回覆|回信|回答|说道|說道|说话|說話|通知|送来|送來|收到|"
            r"发来|發來|写道|寫道|鞠躬|响应|響應))|"
            r"(?:(?:信息|消息|邮件|郵件|联络|聯絡|传话|傳話).{0,12}女[仆僕][酱醬])",
            text,
        )
    )


def nearest_narration(paragraphs: Sequence[str], index: int, distance: int = 3) -> str:
    """Find nearby non-message narration before a candidate message."""
    for step in range(1, distance + 1):
        candidate = index - step
        if candidate >= 0 and message_text(paragraphs[candidate]) is None:
            return paragraphs[candidate]
    return ""


def message_scenes(
    paragraphs: Sequence[str], maximum_narration_gap: int = 3
) -> Iterable[list[int]]:
    """Group electronic messages separated by short narrative reactions."""
    indices = [
        index
        for index, paragraph in enumerate(paragraphs)
        if message_text(paragraph) is not None
    ]
    if not indices:
        return
    scene = [indices[0]]
    for index in indices[1:]:
        narration_gap = index - scene[-1] - 1
        if narration_gap <= maximum_narration_gap:
            scene.append(index)
        else:
            yield scene
            scene = [index]
    yield scene


def infer_turn_roles(
    texts: Sequence[str], paragraphs: Sequence[str], indices: Sequence[int]
) -> tuple[list[str], str, list[str]]:
    """Infer roles and return (roles, confidence, evidence)."""
    roles = ["unknown"] * len(texts)
    evidence: set[str] = set()
    high_anchor = False
    medium_anchor = False

    for i, (text, paragraph_index) in enumerate(zip(texts, indices, strict=True)):
        if MAID_SELF_RE.search(text):
            roles[i] = "maid_chan"
            high_anchor = True
            evidence.add("explicit_maid_self_reference_or_signoff")
            continue
        if re.search(r"(?:空太|龙之介|龍之介)大人", text):
            roles[i] = "maid_chan"
            medium_anchor = True
            evidence.add("maid_honorific_speech_pattern")
            continue
        if re.search(r"(?:拜托|拜託|喂|那么|那麼|问|問).{0,8}女[仆僕][酱醬]?", text):
            roles[i] = "user"
            medium_anchor = True
            evidence.add("message_addresses_maid")
            continue
        narration = nearest_narration(paragraphs, paragraph_index, distance=2)
        if is_maid_narration(narration):
            roles[i] = "maid_chan"
            medium_anchor = True
            evidence.add("adjacent_narration_attributes_message_to_maid")

    # A message immediately preceding an attributed Maid response is its request
    # unless the previous message is independently attributed to Maid as well.
    # Do not propagate alternation through an entire scene: meeting logs and
    # group chats can contain many human speakers.
    for i in range(1, len(roles)):
        if roles[i] == "maid_chan" and roles[i - 1] == "unknown":
            roles[i - 1] = "user"
            evidence.add("request_precedes_attributed_maid_turn")

    if high_anchor:
        confidence = "high"
    elif medium_anchor:
        confidence = "medium"
    else:
        confidence = "low"
        evidence.add("name_mention_only")
    return roles, confidence, sorted(evidence)


def context_slice(paragraphs: Sequence[str], start: int, end: int) -> list[str]:
    """Return a bounded paragraph slice for source context fields."""
    return list(paragraphs[max(0, start) : min(len(paragraphs), end)])


def context_records(
    book: Path, document: Document, context_window: int
) -> Iterable[dict[str, object]]:
    """Yield records for explicit Maid-chan mentions with surrounding context."""
    paragraphs = document.paragraphs
    for index, paragraph in enumerate(paragraphs):
        if not MAID_NAME_RE.search(paragraph):
            continue
        yield {
            "id": stable_id(book.name, document.path, index, "context"),
            "source": {
                "book": book.stem,
                "epub_file": book.name,
                "document": document.path,
                "document_title": document.title,
                "paragraph_index": index,
            },
            "context_before": context_slice(
                paragraphs, index - context_window, index
            ),
            "matched_paragraph": paragraph,
            "context_after": context_slice(
                paragraphs, index + 1, index + 1 + context_window
            ),
        }


def conversation_records(
    book: Path, document: Document, context_window: int
) -> Iterable[dict[str, object]]:
    """Yield attributed message-scene records involving Maid-chan."""
    paragraphs = document.paragraphs
    for indices in message_scenes(paragraphs):
        start, end = indices[0], indices[-1] + 1
        texts = [message_text(paragraphs[index]) or "" for index in indices]
        nearby = context_slice(paragraphs, start - 3, end + 3)
        if not any(MAID_NAME_RE.search(item) for item in texts) and not any(
            is_maid_narration(item) for item in nearby
        ) and not any(MAID_SELF_RE.search(item) for item in texts):
            continue
        roles, confidence, evidence = infer_turn_roles(
            texts, paragraphs, indices
        )
        if "maid_chan" not in roles:
            continue
        yield {
            "id": stable_id(book.name, document.path, start, end, "conversation"),
            "source": {
                "book": book.stem,
                "epub_file": book.name,
                "document": document.path,
                "document_title": document.title,
                "paragraph_start": start,
                "paragraph_end_exclusive": end,
                "message_paragraphs": list(indices),
            },
            "confidence": confidence,
            "evidence": evidence,
            "context_before": context_slice(
                paragraphs, start - context_window, start
            ),
            "turns": [
                {
                    "role": role,
                    "text": turn,
                    "source_paragraph_index": paragraph_index,
                }
                for role, turn, paragraph_index in zip(
                    roles, texts, indices, strict=True
                )
            ],
            "context_after": context_slice(
                paragraphs, end, end + context_window
            ),
        }


def write_jsonl(path: Path, records: Sequence[dict[str, object]]) -> None:
    """Write records as compact UTF-8 JSON Lines."""
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            json.dump(record, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")


def fewshot_records(
    conversations: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Create standard user/assistant pairs from attributed conversation turns."""
    examples: list[dict[str, object]] = []
    for conversation in conversations:
        turns = conversation["turns"]
        if not isinstance(turns, list):
            continue
        for index in range(1, len(turns)):
            request = turns[index - 1]
            response = turns[index]
            if not isinstance(request, dict) or not isinstance(response, dict):
                continue
            if request.get("role") != "user" or response.get("role") != "maid_chan":
                continue
            source = dict(conversation["source"])
            source["request_paragraph_index"] = request["source_paragraph_index"]
            source["response_paragraph_index"] = response["source_paragraph_index"]
            examples.append(
                {
                    "id": stable_id(conversation["id"], index, "fewshot"),
                    "character": "maid_chan",
                    "confidence": conversation["confidence"],
                    "source": source,
                    "messages": [
                        {"role": "user", "content": request["text"]},
                        {"role": "assistant", "content": response["text"]},
                    ],
                }
            )
    return examples


def relative_display(path: Path, base: Path) -> str:
    """Return a project-relative display path when possible."""
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse extractor command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path("corpus/sources"),
        help="directory containing EPUB files (default: corpus/sources)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("corpus"),
        help="output directory (default: corpus)",
    )
    parser.add_argument(
        "--context-window",
        type=int,
        default=3,
        help="number of surrounding paragraphs to retain (default: 3)",
    )
    parser.add_argument(
        "--minimum-confidence",
        choices=("low", "medium", "high"),
        default="medium",
        help="minimum confidence for conversation output (default: medium)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run corpus extraction and write JSONL outputs plus a manifest."""
    args = parse_args(argv)
    if args.context_window < 0:
        raise SystemExit("--context-window must be non-negative")
    if not args.sources.is_dir():
        raise SystemExit(f"source directory does not exist: {args.sources}")

    books = sorted(args.sources.glob("*.epub"), key=lambda path: path.name)
    if not books:
        raise SystemExit(f"no EPUB files found in: {args.sources}")

    contexts: list[dict[str, object]] = []
    conversations: list[dict[str, object]] = []
    per_book: list[dict[str, object]] = []
    confidence_rank = {"low": 0, "medium": 1, "high": 2}

    for book in books:
        documents = read_epub(book)
        book_contexts = [
            record
            for document in documents
            for record in context_records(book, document, args.context_window)
        ]
        book_conversations = [
            record
            for document in documents
            for record in conversation_records(book, document, args.context_window)
            if confidence_rank[str(record["confidence"])]
            >= confidence_rank[args.minimum_confidence]
        ]
        contexts.extend(book_contexts)
        conversations.extend(book_conversations)
        per_book.append(
            {
                "epub_file": book.name,
                "documents_read": len(documents),
                "explicit_mention_contexts": len(book_contexts),
                "conversations": len(book_conversations),
            }
        )

    args.output.mkdir(parents=True, exist_ok=True)
    fewshots = fewshot_records(conversations)
    fewshots_path = args.output / "maid_chan_fewshot.jsonl"
    conversations_path = args.output / "maid_chan_conversations.jsonl"
    contexts_path = args.output / "maid_chan_contexts.jsonl"
    manifest_path = args.output / "maid_chan_manifest.json"
    write_jsonl(fewshots_path, fewshots)
    write_jsonl(conversations_path, conversations)
    write_jsonl(contexts_path, contexts)

    project_root = Path.cwd()
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "extractor": relative_display(Path(__file__), project_root),
        "settings": {
            "sources": relative_display(args.sources, project_root),
            "output": relative_display(args.output, project_root),
            "context_window": args.context_window,
            "minimum_confidence": args.minimum_confidence,
        },
        "outputs": {
            fewshots_path.name: len(fewshots),
            conversations_path.name: len(conversations),
            contexts_path.name: len(contexts),
        },
        "books": per_book,
    }
    with manifest_path.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        output.write("\n")

    print(
        f"Extracted {len(fewshots)} few-shot pairs, {len(conversations)} "
        f"conversations, and {len(contexts)} mention contexts from "
        f"{len(books)} EPUBs into {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
