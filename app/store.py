"""JSON 文件会话存储（黑客松简化版）。"""

import json
from pathlib import Path
from typing import Optional
from app.models import ChatSession

DATA_DIR = Path("data/sessions")


class SessionStore:
    """基于 JSON 文件的会话存储"""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session: ChatSession) -> None:
        path = self.data_dir / f"{session.session_id}.json"
        path.write_text(session.model_dump_json(indent=2), encoding="utf-8")

    def get(self, session_id: str) -> Optional[ChatSession]:
        path = self.data_dir / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ChatSession(**data)

    def list_all(self) -> list[str]:
        return [p.stem for p in self.data_dir.glob("*.json")]
