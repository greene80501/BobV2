from __future__ import annotations

from dataclasses import dataclass
import re
from shutil import get_terminal_size
from typing import Iterable

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from bob.tui.markdown_nodes import (
    BlockNode,
    BlockQuote,
    BulletList,
    CodeBlock,
    CodeSpan,
    Document,
    Emphasis,
    HardBreak,
    Heading,
    InlineNode,
    Link,
    ListItem,
    OrderedList,
    Paragraph,
    SoftBreak,
    Strike,
    Strong,
    Text,
    ThematicBreak,
)


@dataclass(frozen=True, slots=True)
class MarkdownRenderStyle:
    reset: str = ""
    dim: str = ""
    bold: str = ""
    underline: str = ""
    strike: str = ""
    border: str = ""
    soft: str = ""
    code: str = ""
    link: str = ""
    emphasis: str = ""
    strong: str = ""
    heading1: str = ""
    heading2: str = ""
    heading3: str = ""


@dataclass(slots=True)
class StreamState:
    pending: str = ""


@dataclass(slots=True)
class RenderChunk:
    rendered: str
    pending: str


class BaseMarkdownEngine:
    _BLOCK_MARKDOWN_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s|>\s|[-*+]\s|\d+\.\s|```|~~~|[-*_]{3,}\s*$)")
    _INLINE_MARKDOWN_RE = re.compile(r"(`|\*\*?|~~|__|\[|!\[|<)")
    _STREAMABLE_BOUNDARY_RE = re.compile(r"\s+")

    def render(self, text: str) -> str:
        raise NotImplementedError

    def _render_stream_text(self, text: str) -> str:
        parts: list[str] = []
        for raw_line in text.splitlines(keepends=True):
            has_newline = raw_line.endswith("\n")
            line = raw_line[:-1] if has_newline else raw_line
            rendered = self.render(line) if line else ""
            parts.append(rendered)
            if has_newline:
                parts.append("\n")
        return "".join(parts)

    def _is_plain_streaming_text(self, text: str) -> bool:
        stripped = text.lstrip()
        if not stripped:
            return False
        if self._BLOCK_MARKDOWN_RE.match(text):
            return False
        if self._INLINE_MARKDOWN_RE.search(text):
            return False
        return True

    def _split_streamable_prefix(self, text: str) -> tuple[str, str]:
        if not self._is_plain_streaming_text(text):
            return "", text

        last_boundary_end = -1
        for match in self._STREAMABLE_BOUNDARY_RE.finditer(text):
            last_boundary_end = match.end()

        if last_boundary_end <= 0:
            return "", text

        return text[:last_boundary_end], text[last_boundary_end:]

    def render_stream_chunk(self, text: str, state: StreamState) -> RenderChunk:
        state.pending += text
        rendered_parts: list[str] = []

        if "\n" in state.pending:
            last_newline = state.pending.rfind("\n")
            ready = state.pending[: last_newline + 1]
            state.pending = state.pending[last_newline + 1 :]
            rendered_parts.append(self._render_stream_text(ready))

        streamable, remainder = self._split_streamable_prefix(state.pending)
        if streamable:
            rendered_parts.append(streamable)
            state.pending = remainder

        return RenderChunk(rendered="".join(rendered_parts), pending=state.pending)

    def flush_stream_tail(self, state: StreamState) -> str:
        if not state.pending:
            return ""
        tail = self.render(state.pending)
        state.pending = ""
        return tail


class LegacyMarkdownEngine(BaseMarkdownEngine):
    def __init__(self, style: MarkdownRenderStyle) -> None:
        self._style = style
        self._ansi_re = re.compile(r"\033\[[0-9;]*m")

    def _wrap(self, text: str, *codes: str) -> str:
        prefix = "".join(code for code in codes if code)
        if not prefix or not text:
            return text
        return f"{prefix}{text}{self._style.reset}"

    def _inline_md(self, text: str) -> str:
        text = re.sub(r"\*\*\*(.+?)\*\*\*", lambda m: self._wrap(m.group(1), self._style.strong, self._style.emphasis), text)
        text = re.sub(r"\*\*(.+?)\*\*", lambda m: self._wrap(m.group(1), self._style.strong), text)
        text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", lambda m: self._wrap(m.group(1), self._style.emphasis), text)
        text = re.sub(r"`([^`\n]+?)`", lambda m: self._wrap(m.group(1), self._style.code), text)
        text = re.sub(r"~~(.+?)~~", lambda m: self._wrap(m.group(1), self._style.strike), text)
        return text

    def _render_line(self, line: str) -> str:
        if re.match(r"^# ", line):
            return self._wrap(self._inline_md(line[2:]), self._style.heading1, self._style.bold, self._style.underline)
        if re.match(r"^## ", line):
            return self._wrap(self._inline_md(line[3:]), self._style.heading2, self._style.bold)
        if re.match(r"^### ", line):
            return self._wrap(self._inline_md(line[4:]), self._style.heading3, self._style.bold)
        if re.match(r"^#{4,} ", line):
            return self._wrap(self._inline_md(re.sub(r"^#{4,} ", "", line)), self._style.bold)
        if re.match(r"^[-*_]{3,}\s*$", line):
            width = max(10, get_terminal_size((80, 24)).columns - 4)
            return self._wrap("─" * width, self._style.border)
        if line.startswith("> "):
            return f"{self._wrap('│', self._style.border)} {self._inline_md(line[2:])}"
        unordered = re.match(r"^(\s*)([-*+]) (.+)$", line)
        if unordered:
            indent, _, content = unordered.groups()
            return f"{indent}{self._wrap('•', self._style.dim)} {self._inline_md(content)}"
        ordered = re.match(r"^(\s*)(\d+)\. (.+)$", line)
        if ordered:
            indent, num, content = ordered.groups()
            return f"{indent}{self._wrap(f'{num}.', self._style.dim)} {self._inline_md(content)}"
        return self._inline_md(line)

    def render(self, text: str) -> str:
        if not text:
            return ""
        return "\n".join(self._render_line(line) for line in text.splitlines())


class MarkdownItEngine(BaseMarkdownEngine):
    def __init__(self, style: MarkdownRenderStyle) -> None:
        self._style = style
        self._md = MarkdownIt("commonmark")

    def parse(self, text: str) -> Document:
        root = SyntaxTreeNode(self._md.parse(text))
        return Document(children=self._convert_blocks(root.children or []))

    def render(self, text: str) -> str:
        if not text:
            return ""
        document = self.parse(text)
        return "\n".join(self._render_blocks(document.children))

    def _convert_blocks(self, nodes: Iterable[SyntaxTreeNode]) -> list[BlockNode]:
        result: list[BlockNode] = []
        for node in nodes:
            converted = self._convert_block(node)
            if converted is None:
                continue
            result.append(converted)
        return result

    def _convert_block(self, node: SyntaxTreeNode) -> BlockNode | None:
        node_type = getattr(node, "type", "")

        if node_type == "paragraph":
            return Paragraph(children=self._convert_inline_nodes(node.children or []))
        if node_type == "heading":
            level = 1
            try:
                tag = getattr(node, "tag", "h1")
                if isinstance(tag, str) and tag.startswith("h"):
                    level = int(tag[1:])
            except Exception:
                level = 1
            return Heading(level=level, children=self._convert_inline_nodes(node.children or []))
        if node_type in {"fence", "code_block"}:
            return CodeBlock(text=getattr(node, "content", ""), info=getattr(node, "info", "") or "")
        if node_type == "blockquote":
            return BlockQuote(children=self._convert_blocks(node.children or []))
        if node_type == "bullet_list":
            items = [self._convert_list_item(child) for child in node.children or [] if getattr(child, "type", "") == "list_item"]
            return BulletList(items=items)
        if node_type == "ordered_list":
            attrs = getattr(node, "attrs", {}) or {}
            start = int(attrs.get("start", 1))
            items = [self._convert_list_item(child) for child in node.children or [] if getattr(child, "type", "") == "list_item"]
            return OrderedList(items=items, start=start)
        if node_type == "hr":
            return ThematicBreak()
        if node_type in {"html_block"}:
            return Paragraph(children=[Text(getattr(node, "content", ""))])

        flattened = self._flatten_text(node)
        if flattened:
            return Paragraph(children=[Text(flattened)])
        return None

    def _convert_list_item(self, node: SyntaxTreeNode) -> ListItem:
        return ListItem(children=self._convert_blocks(node.children or []))

    def _convert_inline_nodes(self, nodes: Iterable[SyntaxTreeNode]) -> list[InlineNode]:
        result: list[InlineNode] = []
        for node in nodes:
            converted = self._convert_inline(node)
            if converted is None:
                continue
            if isinstance(converted, list):
                result.extend(converted)
            else:
                result.append(converted)
        return result

    def _convert_inline(self, node: SyntaxTreeNode) -> InlineNode | list[InlineNode] | None:
        node_type = getattr(node, "type", "")

        if node_type == "inline":
            return self._convert_inline_nodes(node.children or [])
        if node_type == "text":
            return Text(getattr(node, "content", ""))
        if node_type == "softbreak":
            return SoftBreak()
        if node_type == "hardbreak":
            return HardBreak()
        if node_type == "code_inline":
            return CodeSpan(getattr(node, "content", ""))
        if node_type == "em":
            return Emphasis(children=self._convert_inline_nodes(node.children or []))
        if node_type == "strong":
            return Strong(children=self._convert_inline_nodes(node.children or []))
        if node_type == "s":
            return Strike(children=self._convert_inline_nodes(node.children or []))
        if node_type == "link":
            attrs = getattr(node, "attrs", {}) or {}
            return Link(
                url=str(attrs.get("href", "")),
                title=str(attrs.get("title", "")),
                children=self._convert_inline_nodes(node.children or []),
            )
        if node_type == "image":
            attrs = getattr(node, "attrs", {}) or {}
            alt = self._flatten_text(node) or "image"
            src = str(attrs.get("src", ""))
            text = alt if not src else f"{alt} ({src})"
            return Text(text)
        if node_type in {"html_inline"}:
            return Text(getattr(node, "content", ""))

        flattened = self._flatten_text(node)
        if flattened:
            return Text(flattened)
        return None

    def _flatten_text(self, node: SyntaxTreeNode) -> str:
        content = getattr(node, "content", "")
        if content:
            return content
        parts: list[str] = []
        for child in getattr(node, "children", []) or []:
            flattened = self._flatten_text(child)
            if flattened:
                parts.append(flattened)
        return "".join(parts)

    def _wrap(self, text: str, *codes: str) -> str:
        prefix = "".join(code for code in codes if code)
        if not prefix or not text:
            return text
        return f"{prefix}{text}{self._style.reset}"

    def _render_blocks(self, blocks: list[BlockNode], indent: str = "", separate: bool = True) -> list[str]:
        lines: list[str] = []
        for block in blocks:
            rendered = self._render_block(block, indent)
            if separate and lines and rendered:
                lines.append("")
            lines.extend(rendered)
        return lines

    def _render_block(self, block: BlockNode, indent: str = "") -> list[str]:
        if isinstance(block, Paragraph):
            return self._indent_lines(self._split_inline_text(self._render_inline_nodes(block.children)), indent)
        if isinstance(block, Heading):
            content = self._render_inline_nodes(block.children)
            if block.level == 1:
                return self._indent_lines([self._wrap(content, self._style.heading1, self._style.bold, self._style.underline)], indent)
            if block.level == 2:
                return self._indent_lines([self._wrap(content, self._style.heading2, self._style.bold)], indent)
            return self._indent_lines([self._wrap(content, self._style.heading3, self._style.bold)], indent)
        if isinstance(block, CodeBlock):
            return self._render_code_block(block, indent)
        if isinstance(block, BlockQuote):
            return self._render_blockquote(block, indent)
        if isinstance(block, BulletList):
            return self._render_bullet_list(block, indent)
        if isinstance(block, OrderedList):
            return self._render_ordered_list(block, indent)
        if isinstance(block, ThematicBreak):
            width = max(10, get_terminal_size((80, 24)).columns - len(indent) - 4)
            return [f"{indent}{self._wrap('─' * width, self._style.border)}"]
        return []

    def _render_bullet_list(self, block: BulletList, indent: str) -> list[str]:
        lines: list[str] = []
        for index, item in enumerate(block.items):
            if index:
                lines.append("")
            lines.extend(self._render_list_item(item, indent, self._wrap("•", self._style.dim)))
        return lines

    def _render_ordered_list(self, block: OrderedList, indent: str) -> list[str]:
        lines: list[str] = []
        number = block.start
        for index, item in enumerate(block.items):
            if index:
                lines.append("")
            marker = self._wrap(f"{number}.", self._style.dim)
            lines.extend(self._render_list_item(item, indent, marker))
            number += 1
        return lines

    def _render_list_item(self, item: ListItem, indent: str, marker: str) -> list[str]:
        body = self._render_blocks(item.children, separate=True)
        if not body:
            return [f"{indent}{marker}"]

        continuation = indent + " " * (self._visible_len(marker) + 1)
        lines: list[str] = []
        first = body[0]
        lines.append(f"{indent}{marker} {first}" if first else f"{indent}{marker}")
        for line in body[1:]:
            lines.append(f"{continuation}{line}" if line else "")
        return lines

    def _render_blockquote(self, block: BlockQuote, indent: str) -> list[str]:
        body = self._render_blocks(block.children, separate=True)
        if not body:
            return [f"{indent}{self._wrap('│', self._style.border)}"]

        prefix = self._wrap("│", self._style.border)
        lines: list[str] = []
        for line in body:
            if line:
                lines.append(f"{indent}{prefix} {line}")
            else:
                lines.append(f"{indent}{prefix}")
        return lines

    def _render_code_block(self, block: CodeBlock, indent: str) -> list[str]:
        info = block.info.strip()
        fence = "```" + info if info else "```"
        lines = [f"{indent}{self._wrap(fence, self._style.dim)}"]
        body_lines = block.text.rstrip("\n").splitlines()
        if not body_lines:
            body_lines = [""]
        lines.extend(f"{indent}{self._wrap(line, self._style.code)}" if line else indent for line in body_lines)
        lines.append(f"{indent}{self._wrap('```', self._style.dim)}")
        return lines

    def _render_inline_nodes(self, nodes: list[InlineNode]) -> str:
        parts: list[str] = []
        for node in nodes:
            parts.append(self._render_inline(node))
        return "".join(parts)

    def _render_inline(self, node: InlineNode) -> str:
        if isinstance(node, Text):
            return node.text
        if isinstance(node, SoftBreak):
            return "\n"
        if isinstance(node, HardBreak):
            return "\n"
        if isinstance(node, Emphasis):
            return self._wrap(self._render_inline_nodes(node.children), self._style.emphasis)
        if isinstance(node, Strong):
            return self._wrap(self._render_inline_nodes(node.children), self._style.strong)
        if isinstance(node, Strike):
            return self._wrap(self._render_inline_nodes(node.children), self._style.strike)
        if isinstance(node, CodeSpan):
            return self._wrap(node.text, self._style.code)
        if isinstance(node, Link):
            label = self._render_inline_nodes(node.children).strip()
            if not label:
                return self._wrap(node.url, self._style.link)
            if label == node.url:
                return self._wrap(label, self._style.link)
            return f"{self._wrap(label, self._style.link)} ({node.url})"
        return ""

    def _split_inline_text(self, text: str) -> list[str]:
        if text == "":
            return [""]
        return text.splitlines() or [""]

    def _indent_lines(self, lines: list[str], indent: str) -> list[str]:
        if not indent:
            return lines
        return [f"{indent}{line}" if line else indent for line in lines]

    def _visible_len(self, text: str) -> int:
        return len(re.sub(r"\033\[[0-9;]*m", "", text))


def create_markdown_engine(name: str, style: MarkdownRenderStyle) -> BaseMarkdownEngine:
    if name == "legacy":
        return LegacyMarkdownEngine(style)
    return MarkdownItEngine(style)
