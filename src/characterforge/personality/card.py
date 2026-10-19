import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_card(path: Path) -> dict:
    card = read_json(path)
    for field in ("id", "display_name", "rules", "background", "variables"):
        if field not in card:
            raise ValueError(f"Character card is missing {field!r}.")
    return card


def system_prompt(card: dict, condition: str) -> str:
    if condition not in ("rules_only", "rules_plus_background"):
        raise ValueError("Unknown prompt condition.")
    text = "\n".join(card["rules"])
    if condition == "rules_plus_background":
        text += "\n\nShort background (originally authored summary):\n" + card["background"]
    return text


class Conversation:
    """Keep successful turns only; reset is explicitly controlled by the caller."""
    def __init__(self, system: str):
        self.messages = [{"role": "system", "content": system}]

    def request_messages(self, user_text: str) -> list[dict]:
        return self.messages + [{"role": "user", "content": user_text}]

    def accept(self, user_text: str, answer: str):
        self.messages.extend([{"role": "user", "content": user_text},
                              {"role": "assistant", "content": answer}])
