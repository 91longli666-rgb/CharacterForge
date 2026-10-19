"""Parse one bounded, leading delivery decision from the same dialogue pass.

Never starts a second LLM request, invents audio, or exposes a control prefix to
the spoken reply. Missing/invalid headers preserve the rule-based fallback.
"""
import re

VOICES={'normal':'normal','smug':'sarcastic','defensive':'sarcastic','annoyed':'sarcastic','angry':'angry'}
HEAT={'normal':0,'smug':0,'defensive':1,'annoyed':2,'angry':4}
INSTRUCTION='''Automatic delivery decision: use this latest message AND recent conversation to decide your own reaction, rather than copying a selected voice. First output exactly one control header [[mood:normal]], [[mood:smug]], [[mood:defensive]], [[mood:annoyed]], or [[mood:angry]], then a newline and the complete spoken reply. The header is hidden from the user and is not spoken.
Use normal for a calm genuine question or a subject change; smug when taking credit, gloating, teasing or enjoying praise; defensive for a challenged ego or an excuse; annoyed for a direct provocation; angry for a serious direct attack or continuing heated argument. Quoted insults, someone else's argument, and a user describing their own bad day are not attacks on you. An apology or a clear subject change can cool you down. Do not choose anger just because a sentence contains profanity. Keep the character's selfish comic personality in every mood. Let your actual reply match the chosen reaction, with natural emphasis; do not write stage directions or further control tags. After the header obey the concrete opening requirement and develop the complete reply at the existing length.'''

class DeliveryHeader:
    LIMIT=96
    def __init__(self):self.buffer='';self.resolved=False;self.mood=None;self.reason='missing_header';self.body_started=False
    def feed(self,text,final=False):
        if self.resolved:
            if not self.body_started:text=text.lstrip();self.body_started=bool(text)
            return text
        self.buffer+=text;value=self.buffer.lstrip();prefix='[[mood:'
        if len(value)<len(prefix) and prefix.startswith(value) and not final:return ''
        if final and value and prefix.startswith(value):raise ValueError('自动语气控制格式未完成，请重新发送。')
        if value.startswith(prefix):
            match=re.match(r'^\[\[mood:([A-Za-z_ -]{1,32})\]\][ \t]*(?:\r?\n)?',value)
            if match:
                mood=match.group(1).lower();self.mood=mood if mood in VOICES else None
                self.reason='model' if self.mood else 'invalid_header'
                self.resolved=True;self.buffer='';body=value[match.end():].lstrip();self.body_started=bool(body);return body
            if len(value)<=self.LIMIT and not final:return ''
            # Never silently discard possible spoken text to repair a malformed
            # prefix. Fail this turn explicitly instead of reading control data.
            raise ValueError('自动语气控制格式未完成，请重新发送；没有截断后继续朗读。')
        self.resolved=True;self.buffer='';self.body_started=bool(value);return value
    def finish(self):return self.feed('',final=True)
    def apply(self,meta):
        result={**meta,'delivery_source':self.reason}
        if self.mood:
            result.update(mood=self.mood,voice_profile=VOICES[self.mood],
                state={**meta['state'],'mood':self.mood,'heat':HEAT[self.mood]})
        return result
