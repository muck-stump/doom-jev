import os
import json
import logging
import httpx
from logging.handlers import RotatingFileHandler
from pydantic import BaseModel
from typing import Optional, List

# ── Logger setup ────────────────────────────────────────────────────────────
_log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)

_handler = RotatingFileHandler(
    os.path.join(_log_dir, "jev_api.log"),
    maxBytes=2 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s\n%(message)s\n" + "─" * 80)
)

log = logging.getLogger("jev_client")
log.setLevel(logging.DEBUG)
log.addHandler(_handler)
# ────────────────────────────────────────────────────────────────────────────


class ChoiceQuestionResponse(BaseModel):
    value: str
    confidence: float
    probabilities: dict[str, float] = {}
    question_text: str = ""

    @classmethod
    def from_api(cls, data: dict, question_text: str = "") -> "ChoiceQuestionResponse":
        val = data.get("choice", data.get("value", "none"))
        conf = float(data.get("confidence", 1.0))
        raw_probs = data.get("probabilities", {})
        probs = {k: float(v) for k, v in raw_probs.items()} if isinstance(raw_probs, dict) else {}
        if not probs and val != "none":
            probs = {val: conf}
        return cls(
            value=val,
            confidence=conf,
            probabilities=probs,
            question_text=question_text,
        )


class NoulQuestionResponse(BaseModel):
    value: bool
    confidence: float
    probabilities: dict[str, float] = {}
    question_text: str = ""

    @classmethod
    def from_api(
        cls,
        data: dict,
        true_label: str = "true",
        false_label: str = "false",
        question_text: str = "",
    ) -> "NoulQuestionResponse":
        raw = data.get("noul", data.get("value", 0.0))
        prob = float(raw) if isinstance(raw, (int, float)) else 0.0
        prob = max(0.0, min(1.0, prob))
        probs = {
            false_label: round(1.0 - prob, 3),
            true_label: round(prob, 3),
        }
        # In UI, confidence can be highest prob or the raw calibrated prob
        return cls(
            value=prob >= 0.5,
            confidence=prob,
            probabilities=probs,
            question_text=question_text,
        )


class JevResponse(BaseModel):
    macro_goal: ChoiceQuestionResponse
    target:     ChoiceQuestionResponse
    movement:   ChoiceQuestionResponse
    rotation:   ChoiceQuestionResponse
    jump:       NoulQuestionResponse
    firing:     NoulQuestionResponse
    raw_answers: dict = {}


class VisibleEnemy:
    def __init__(self, label: str):
        self.label = str(label)

    def __repr__(self) -> str:
        return f"VisibleEnemy({self.label})"

    def __eq__(self, other) -> bool:
        if isinstance(other, VisibleEnemy):
            return self.label == other.label
        return self.label == str(other)

    def __hash__(self) -> int:
        return hash(self.label)


class JevClient:
    def __init__(self):
        self.api_key = os.getenv("TYPESAFE_API_KEY")
        self.url = "https://api.typesafe.ai/v1/systemone"
        self.client = httpx.AsyncClient(timeout=1.5)

    async def get_decision(
        self, state_yaml: str, visible_enemies: List[Any]
    ) -> Optional[JevResponse]:
        if not self.api_key:
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Normalize elements so each has .label
        enemies_with_labels = [
            e if hasattr(e, "label") else VisibleEnemy(str(e))
            for e in visible_enemies
        ]

        payload = {
            "model": "jev-latest",
            "state": state_yaml,
            "questions": {
                "macro_goal": {
                    "type": "choice",
                    "criteria": {
                        "engage": "Push forward and eliminate enemies that are in direct line of sight.",
                        "collect_weapon": "Navigate specifically to pick up a stronger weapon in the room.",
                        "explore": "Navigate safely, finding resources and turning away from dead ends or walls.",
                        "flee": "Retreat immediately to survive heavy incoming damage.",
                    },
                    "instructions": "What is the player's overarching objective right now?",
                },
                "target": {
                    "type": "choice",
                    "criteria": {e.label: f"Acquire {e.label} in crosshair" for e in enemies_with_labels} or {"none": "No valid targets"},
                    "instructions": "Which enemy in direct line of sight should the player aim at? Select 'none' if all enemies are behind walls.",
                },
                "movement": {
                    "type": "choice",
                    "criteria": {
                        "forward": "Advance towards the objective.",
                        "backward": "Backpedal from danger or a blocked path.",
                        "left": "Strafe left to dodge or navigate around an obstructing wall.",
                        "right": "Strafe right to dodge or navigate around an obstructing wall.",
                        "none": "Hold current position.",
                    },
                    "instructions": "Which directional movement should the player execute considering current obstacles and walls?",
                },
                "rotation": {
                    "type": "choice",
                    "criteria": {
                        "turn_left": "Rotate left to track a target or turn away from a wall directly in front.",
                        "turn_right": "Rotate right to track a target or turn away from a wall directly in front.",
                        "none": "Keep current angle; path is clear and target is centered.",
                    },
                    "instructions": "How should the player rotate to aim or avoid walking into a wall?",
                },
                "jump": {
                    "type": "noul",
                    "instructions": "Should the player jump right now to clear an obstacle, gap, or incoming projectile?",
                },
                "firing": {
                    "type": "noul",
                    "instructions": "Should the trigger be held down to spam fire? Only return high confidence if a target is near the crosshair and NOT obstructed by a wall.",
                },
            },
        }

        try:
            log.debug(
                "── OUTBOUND REQUEST ──\n"
                f"URL: {self.url}\n"
                f"PAYLOAD:\n{json.dumps(payload, indent=2)}"
            )
            response = await self.client.post(self.url, json=payload, headers=headers)
            log.debug(
                f"── RAW RESPONSE [HTTP {response.status_code}] ──\n"
                f"{response.text}"
            )
            response.raise_for_status()
            data = response.json()
            answers = data.get("answers", {})

            q_cfg = payload.get("questions", {})
            return JevResponse(
                macro_goal=ChoiceQuestionResponse.from_api(
                    answers.get("macro_goal", {"choice": "explore", "confidence": 1.0}),
                    question_text=q_cfg.get("macro_goal", {}).get("instructions", "What is the player's overarching objective right now?"),
                ),
                target=ChoiceQuestionResponse.from_api(
                    answers.get("target", {"choice": "none", "confidence": 1.0}),
                    question_text=q_cfg.get("target", {}).get("instructions", "Which enemy in line of sight should the player aim at?"),
                ),
                movement=ChoiceQuestionResponse.from_api(
                    answers.get("movement", {"choice": "forward", "confidence": 1.0}),
                    question_text=q_cfg.get("movement", {}).get("instructions", "Which directional movement should the player execute?"),
                ),
                rotation=ChoiceQuestionResponse.from_api(
                    answers.get("rotation", {"choice": "none", "confidence": 1.0}),
                    question_text=q_cfg.get("rotation", {}).get("instructions", "How should the player rotate to aim or avoid walls?"),
                ),
                jump=NoulQuestionResponse.from_api(
                    answers.get("jump", {"noul": 0.0}),
                    true_label="jump",
                    false_label="stay_grounded",
                    question_text=q_cfg.get("jump", {}).get("instructions", "Should the player jump right now?"),
                ),
                firing=NoulQuestionResponse.from_api(
                    answers.get("firing", {"noul": 0.0}),
                    true_label="fire",
                    false_label="hold_fire",
                    question_text=q_cfg.get("firing", {}).get("instructions", "Should the player's trigger be held down right now?"),
                ),
                raw_answers=answers,
            )
        except Exception as e:
            log.error(
                f"── API ERROR ──\n"
                f"Type: {type(e).__name__}\n"
                f"Detail: {e}"
            )
            return None

    async def close(self):
        await self.client.aclose()
