from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InlineNode:
    pass


@dataclass(slots=True)
class BlockNode:
    pass


@dataclass(slots=True)
class Document:
    children: list[BlockNode] = field(default_factory=list)


@dataclass(slots=True)
class Text(InlineNode):
    text: str


@dataclass(slots=True)
class Emphasis(InlineNode):
    children: list[InlineNode] = field(default_factory=list)


@dataclass(slots=True)
class Strong(InlineNode):
    children: list[InlineNode] = field(default_factory=list)


@dataclass(slots=True)
class Strike(InlineNode):
    children: list[InlineNode] = field(default_factory=list)


@dataclass(slots=True)
class CodeSpan(InlineNode):
    text: str


@dataclass(slots=True)
class Link(InlineNode):
    url: str
    title: str = ""
    children: list[InlineNode] = field(default_factory=list)


@dataclass(slots=True)
class SoftBreak(InlineNode):
    pass


@dataclass(slots=True)
class HardBreak(InlineNode):
    pass


@dataclass(slots=True)
class Paragraph(BlockNode):
    children: list[InlineNode] = field(default_factory=list)


@dataclass(slots=True)
class Heading(BlockNode):
    level: int
    children: list[InlineNode] = field(default_factory=list)


@dataclass(slots=True)
class CodeBlock(BlockNode):
    text: str
    info: str = ""


@dataclass(slots=True)
class BlockQuote(BlockNode):
    children: list[BlockNode] = field(default_factory=list)


@dataclass(slots=True)
class ListItem(BlockNode):
    children: list[BlockNode] = field(default_factory=list)


@dataclass(slots=True)
class BulletList(BlockNode):
    items: list[ListItem] = field(default_factory=list)


@dataclass(slots=True)
class OrderedList(BlockNode):
    items: list[ListItem] = field(default_factory=list)
    start: int = 1


@dataclass(slots=True)
class ThematicBreak(BlockNode):
    pass
