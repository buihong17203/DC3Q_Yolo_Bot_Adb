from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from app.vision import VisionDetector

@dataclass
class StateDefinition:
    name: str
    templates: list[str] = field(default_factory=list)
    threshold: float = 0.85

@dataclass
class DetectedState:
    name: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

class StateDetector:
    def __init__(self, vision: VisionDetector | None = None):
        self.vision = vision or VisionDetector()
    def detect(self, screen: Any, states: list[StateDefinition]) -> DetectedState | None:
        best = None
        for state in states:
            evid=[]; scores=[]
            for template in state.templates:
                m=self.vision.find_template(screen, state.name, template, state.threshold).match
                if m.found: evid.append(template)
                scores.append(m.confidence)
            if scores:
                score=max(scores)
                if best is None or score > best.confidence:
                    best=DetectedState(state.name, score, evid)
        return best
