from dataclasses import dataclass


@dataclass
class PvfCommentPayload:
    rules: list[str]
    languages: list[str]
    fps: bool
    all_flag: bool
