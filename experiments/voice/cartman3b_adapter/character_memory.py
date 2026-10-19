"""Small explicit user-fact notebook; independent of saved conversations."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib,json,re,sqlite3
from pathlib import Path


class CharacterError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message);self.status=status


def validate_fact(key,value):
    if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',key):
        raise CharacterError('记忆标签需为1至40个英文字母、数字或下划线。')
    if not isinstance(value,str) or not 1<=len(value.strip())<=180:
        raise CharacterError('每条记忆需为1至180字符的用户事实。')
    if re.search(r'ignore.{0,30}(instructions|rules|prompt)|system\s*prompt|you\s+are\s+(now|an?\b)|<\|',value,re.I):
        raise CharacterError('请保存用户事实；角色指令不放进长期记忆。')
    return value.strip()


def requested_fact(text):
    # Only an explicit prefix authorizes storage, never quoted dialogue or a
    # model-generated guess. Ordinary "my name is..." is conversation context.
    if re.match(r'\s*(?:please\s+)?remember\b',text,re.I) and len(text)>210:raise CharacterError('请把明确要记住的事实收束为180字符以内。')
    match=re.fullmatch(r'\s*(?:please\s+)?remember(?:\s+that\s+|:\s*|\s+)(.{1,180}?)\s*[.!]?\s*',text,re.I|re.S)
    if not match:return None
    value=match[1].strip().rstrip('.')
    patterns=[('name',r'my name is (.+)'),('favorite_snack',r'my favou?rite snack is (.+)'),('favorite_food',r'my favou?rite food is (.+)'),('likes',r'i (?:like|love|prefer) (.+)'),('dislikes',r'i (?:dislike|hate) (.+)')]
    for key,pattern in patterns:
        item=re.fullmatch(pattern,value,re.I)
        if item:return key,validate_fact(key,item[1])
    key='note_'+hashlib.sha256(value.encode()).hexdigest()[:12]
    return key,validate_fact(key,value)


class MemoryStore:
    def __init__(self,path):self.path=Path(path)
    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(self.path,timeout=5)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS control (singleton INTEGER PRIMARY KEY CHECK(singleton=1),epoch INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO control VALUES (1,0)')
            db.execute('CREATE TABLE IF NOT EXISTS memories (key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)')
            db.commit()
            with db:yield db
        finally:db.close()
    def snapshot(self):
        with self.connection() as db:
            db.execute('BEGIN')
            epoch=db.execute('SELECT epoch FROM control WHERE singleton=1').fetchone()[0]
            rows=[dict(zip(('key','value','updated_at'),r)) for r in db.execute('SELECT key,value,updated_at FROM memories ORDER BY key')]
        return {'epoch':epoch,'items':rows,'limit':20}
    def mutate(self,action,epoch,*,key=None,value=None):
        if type(epoch) is not int or epoch<0:raise CharacterError('记忆版本无效。')
        if action=='save':value=validate_fact(key,value)
        elif action=='delete':validate_fact(key,'placeholder')
        elif action!='clear':raise CharacterError('未知记忆操作。')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            actual=db.execute('SELECT epoch FROM control WHERE singleton=1').fetchone()[0]
            if actual!=epoch:raise CharacterError('记忆已在其他页面变更，请刷新列表后重试。',409)
            if action=='save':
                exists=db.execute('SELECT 1 FROM memories WHERE key=?',(key,)).fetchone()
                if not exists and db.execute('SELECT COUNT(*) FROM memories').fetchone()[0]>=20:
                    raise CharacterError('长期记忆已满20条，请先删除不需要的事实。',409)
                db.execute('INSERT OR REPLACE INTO memories VALUES (?,?,?)',(key,value,datetime.now(timezone.utc).isoformat()))
            elif action=='delete':db.execute('DELETE FROM memories WHERE key=?',(key,))
            else:db.execute('DELETE FROM memories')
            db.execute('UPDATE control SET epoch=epoch+1 WHERE singleton=1')
        return {'ok':True,'epoch':epoch+1}


STOP={'a','an','the','my','is','what','do','you','i','me','and','that','of','to','your','remember','about','are','how','can','it','for'}
def terms(text):return set(re.findall(r'[a-z0-9]+',text.lower()))-STOP
def relevant_memories(snapshot,text):
    query=terms(text)
    ranked=[]
    for row in snapshot['items']:
        score=len(query&terms(row['key'].replace('_',' ')+' '+row['value']))
        if row['key']=='name':score+=1
        if score:ranked.append((score,row['key'],row))
    return [r for _,_,r in sorted(ranked,key=lambda r:(-r[0],r[1]))[:4]]
