"""Local recent conversations for P4. No semantic or long-term memory."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

DEFAULT_PATH = Path(os.environ.get('CF_STATE_ROOT',Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge'))/'.local')) / 'p4/conversations.sqlite3'
MODES = ('adapter', 'base', 'roast8b')
STYLES = ('character', 'original', 'spoken')
DELIVERIES = ('normal', 'sarcastic', 'angry')


class HistoryError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise HistoryError('会话编号无效。')
    return value


class ConversationStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL, messages TEXT NOT NULL, settings TEXT NOT NULL)')
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connection() as db:
            return [dict(zip(('id', 'title', 'updated_at', 'revision'), row)) for row in db.execute('SELECT id,title,updated_at,revision FROM conversations ORDER BY updated_at DESC,id LIMIT 100')]

    def get(self, session_id):
        valid_id(session_id)
        with self.connection() as db:
            row = db.execute('SELECT title,updated_at,revision,messages,settings FROM conversations WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise HistoryError('该会话已删除或不存在。', 404)
        return dict(id=session_id, title=row[0], updated_at=row[1], revision=row[2], messages=json.loads(row[3]), settings=json.loads(row[4]))

    def save(self, payload):
        if set(payload) != {'id', 'revision', 'messages', 'settings'}:
            raise HistoryError('会话保存参数无效。')
        session_id, revision = payload['id'], payload['revision']
        if session_id is not None:
            valid_id(session_id)
        if type(revision) is not int or revision < 0 or (session_id is None and revision != 0):
            raise HistoryError('会话版本无效。')
        messages, settings = payload['messages'], payload['settings']
        if not isinstance(messages, list) or not 1 <= len(messages) <= 200:
            raise HistoryError('每段会话可保存1至200条消息；记录满后请开始新对话。')
        for message in messages:
            if (not isinstance(message, dict) or not {'role','content'}<=set(message) or set(message)-{'role','content','voice_profile'}
                    or message['role'] not in ('user', 'assistant')
                    or not isinstance(message['content'], str) or not message['content'].strip()
                    or len(message['content']) > 6000):
                raise HistoryError('消息格式或长度无效。')
            if 'voice_profile' in message and (message['role']!='assistant' or not isinstance(message['voice_profile'],str) or message['voice_profile'] not in DELIVERIES):raise HistoryError('消息语气无效。')
        if messages[0]['role'] != 'user':
            raise HistoryError('会话需以你的消息开始。')
        if (not isinstance(settings, dict) or not {'mode', 'reply_style', 'delivery'} <= set(settings)
                or set(settings)-{'mode','reply_style','delivery','emotion_mode','character_state','memory_enabled','emotion_control_version'}
                or settings['mode'] not in MODES or settings['reply_style'] not in STYLES
                or settings['delivery'] not in DELIVERIES):
            raise HistoryError('会话设置无效。')
        if 'emotion_mode' in settings and settings['emotion_mode'] not in ('auto','manual'):raise HistoryError('自动情绪设置无效。')
        if 'emotion_control_version' in settings and (type(settings['emotion_control_version']) is not int or settings['emotion_control_version']!=2):raise HistoryError('自动语气版本无效。')
        if 'memory_enabled' in settings and type(settings['memory_enabled']) is not bool:raise HistoryError('记忆设置无效。')
        if 'character_state' in settings:
            from character_runtime import clean_state
            try:clean_state(settings['character_state'])
            except ValueError:raise HistoryError('情绪状态无效。')
        encoded = json.dumps(messages, ensure_ascii=False)
        if len(encoded.encode('utf-8')) > 1024 * 1024:
            raise HistoryError('这段会话过长，请导出后开始新对话。')
        encoded_settings = json.dumps(settings, sort_keys=True)
        title = ' '.join(messages[0]['content'].split())[:72]
        updated = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if session_id is None:
                if db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] >= 100:
                    raise HistoryError('已保存100段会话，请删除不需要的记录后再保存。', 409)
                session_id = uuid.uuid4().hex
                db.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?)', (session_id, title, updated, 1, encoded, encoded_settings))
                revision = 1
            else:
                row = db.execute('SELECT revision,messages,settings FROM conversations WHERE id=?', (session_id,)).fetchone()
                if row is None:
                    raise HistoryError('会话已删除；当前文字仍可导出，或开始新对话。', 404)
                if row[0] != revision:
                    if row[1] == encoded and row[2] == encoded_settings:
                        return {'id': session_id, 'revision': row[0]}
                    raise HistoryError('另一个页面修改了此会话。请先导出当前文字，再重新载入记录。', 409)
                revision += 1
                db.execute('UPDATE conversations SET title=?,updated_at=?,revision=?,messages=?,settings=? WHERE id=?', (title, updated, revision, encoded, encoded_settings, session_id))
        return {'id': session_id, 'revision': revision}

    def delete(self, session_id, revision):
        valid_id(session_id)
        if type(revision) is not int or revision < 1:
            raise HistoryError('会话版本无效。')
        with self.connection() as db:
            result = db.execute('DELETE FROM conversations WHERE id=? AND revision=?', (session_id, revision))
            if not result.rowcount:
                raise HistoryError('会话已变更或删除，请重新载入列表。', 409)
        return {'ok': True}
