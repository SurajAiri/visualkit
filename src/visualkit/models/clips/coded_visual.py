from enum import Enum
from typing import Literal

from pydantic import Field

from .media import MediaClip


class CompileStatus(str, Enum):
    PENDING = "pending"
    COMPILING = "compiling"
    READY = "ready"
    FAILED = "failed"


class CodedVisualClip(MediaClip):
    clip_type: Literal["coded_visual"] = "coded_visual"
    compile_status: CompileStatus = Field(default=CompileStatus.PENDING)
