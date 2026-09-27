from __future__ import annotations
from dataclasses import dataclass
from .template import TemplateMatcher, MatchResult

@dataclass
class Detection:
    name: str
    match: MatchResult

class VisionDetector:
    def __init__(self, matcher: TemplateMatcher | None = None):
        self.matcher = matcher or TemplateMatcher()
    def find_template(self, screen, name: str, template, threshold: float = 0.85) -> Detection:
        return Detection(name, self.matcher.match(screen, template, threshold))
