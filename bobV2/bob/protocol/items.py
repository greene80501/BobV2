from __future__ import annotations
from typing import Annotated, Literal, Optional, Any, Union
from pydantic import BaseModel, Field
from pathlib import Path


# ---------------------------------------------------------------------------
# Content items
# ---------------------------------------------------------------------------

class InputTextContent(BaseModel):
    type: Literal["input_text"] = "input_text"
    text: str


class InputImageContent(BaseModel):
    type: Literal["input_image"] = "input_image"
    image_url: str  # file:// or https:// or base64 data URL


class OutputTextContent(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str


ContentItem = Annotated[
    Union[InputTextContent, InputImageContent, OutputTextContent],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# User input types (what can be in UserTurnOp.items)
# ---------------------------------------------------------------------------

class TextUserInput(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageUserInput(BaseModel):
    type: Literal["image"] = "image"
    path: Path  # local image path


UserInput = Annotated[
    Union[TextUserInput, ImageUserInput],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Tool use block (inside an assistant message)
# ---------------------------------------------------------------------------

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


# ---------------------------------------------------------------------------
# Message items (what goes in history / Responses API input)
# ---------------------------------------------------------------------------

class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: list[Union[InputTextContent, InputImageContent]]


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: list[Union[OutputTextContent, ToolUseBlock]]


class ToolResultMessage(BaseModel):
    role: Literal["tool"] = "tool"
    tool_call_id: str
    content: str


class DeveloperMessage(BaseModel):
    role: Literal["developer"] = "developer"
    content: list[InputTextContent]


ResponseItem = Union[UserMessage, AssistantMessage, ToolResultMessage, DeveloperMessage]


# ---------------------------------------------------------------------------
# File change (for patch approval)
# ---------------------------------------------------------------------------

class FileChange(BaseModel):
    path: str
    change_type: str  # "add" | "update" | "delete" | "move"
    old_path: Optional[str] = None  # for moves
    diff_preview: Optional[str] = None  # first N lines of diff for display


# ---------------------------------------------------------------------------
# Rollout storage wrapper
# ---------------------------------------------------------------------------

class RolloutResponseItem(BaseModel):
    type: Literal["response_item"] = "response_item"
    item: dict  # serialized ResponseItem


# ---------------------------------------------------------------------------
# Skill types
# ---------------------------------------------------------------------------

class SkillInterface(BaseModel):
    display_name: Optional[str] = None
    short_description: Optional[str] = None
    icon_small: Optional[str] = None
    icon_large: Optional[str] = None
    brand_color: Optional[str] = None
    default_prompt: Optional[str] = None


class SkillToolDependency(BaseModel):
    type: str  # "tool" | "mcp" | "connector"
    value: str
    description: Optional[str] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    url: Optional[str] = None


class SkillDependencies(BaseModel):
    tools: list[SkillToolDependency] = Field(default_factory=list)


class SkillMetadata(BaseModel):
    name: str
    description: str
    short_description: Optional[str] = None
    interface: Optional[SkillInterface] = None
    dependencies: Optional[SkillDependencies] = None
    path: Path
    scope: str  # SkillScope value
    enabled: bool = True
    # Claude Code / SKILL.md compatibility fields
    user_invocable: bool = False
    allowed_tools: list[str] = Field(default_factory=list)
    content_file: str = "skill.md"  # "skill.md" (bob) or "SKILL.md" (Claude Code)


class SkillErrorInfo(BaseModel):
    path: str
    error: str


class SkillsListEntry(BaseModel):
    cwd: Path
    skills: list[SkillMetadata] = Field(default_factory=list)
    errors: list[SkillErrorInfo] = Field(default_factory=list)
