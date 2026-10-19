from pathlib import Path
import sys,unittest
S=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'cartman3b_adapter'
sys.path.insert(0,str(S))
from adaptive_delivery import DeliveryHeader,VOICES
from conversation_store import ConversationStore,HistoryError
import tempfile

class AdaptiveTests(unittest.TestCase):
 def test_every_network_split_preserves_complete_body(self):
  body="Your snack policy is bullshit, and here's why. Keep every word!"
  for mood in VOICES:
   wire='[[mood:'+mood+']]\n'+body
   for i in range(len(wire)+1):
    p=DeliveryHeader();text=p.feed(wire[:i])+p.feed(wire[i:])+p.finish()
    self.assertEqual(text,body);self.assertEqual(p.mood,mood)
 def test_one_character_network_chunks(self):
  p=DeliveryHeader();text=''.join(p.feed(x) for x in '[[mood:angry]]\nNo missing words.');text+=p.finish()
  self.assertEqual(text,'No missing words.');self.assertEqual(p.reason,'model')
 def test_no_header_keeps_prose_and_rule_fallback(self):
  p=DeliveryHeader();self.assertEqual(p.feed('A complete reply.')+p.finish(),'A complete reply.')
  meta={'state':{'mood':'annoyed','heat':2,'turns':1},'voice_profile':'sarcastic'}
  self.assertEqual(p.apply(meta)['voice_profile'],'sarcastic');self.assertEqual(p.apply(meta)['delivery_source'],'missing_header')
 def test_unknown_closed_header_falls_back_without_reading_metadata(self):
  p=DeliveryHeader();self.assertEqual(p.feed('[[mood:invented]]\nKeep this full sentence.'),'Keep this full sentence.')
  self.assertIsNone(p.mood);self.assertEqual(p.reason,'invalid_header')
 def test_incomplete_or_oversized_header_fails_instead_of_truncating_text(self):
  for text in ('[[mood:angry','[[mood:'+'x'*100):
   with self.assertRaises(ValueError):p=DeliveryHeader();p.feed(text);p.finish()
 def test_model_decision_controls_voice_and_next_state(self):
  for mood,profile in VOICES.items():
   p=DeliveryHeader();p.feed('[[mood:'+mood+']]\nReply.')
   result=p.apply({'state':{'mood':'angry','heat':4,'turns':7},'voice_profile':'angry'})
   self.assertEqual(result['voice_profile'],profile);self.assertEqual(result['state']['mood'],mood);self.assertEqual(result['state']['turns'],7)
 def test_saved_per_reply_profile_and_explicit_new_manual_mode(self):
  with tempfile.TemporaryDirectory() as d:
   store=ConversationStore(Path(d)/'sessions.sqlite3')
   settings={'mode':'adapter','reply_style':'character','delivery':'normal','emotion_mode':'manual','emotion_control_version':2}
   messages=[{'role':'user','content':'Hello'},{'role':'assistant','content':'Hello back.','voice_profile':'angry'}]
   saved=store.save({'id':None,'revision':0,'messages':messages,'settings':settings})
   again=store.get(saved['id']);self.assertEqual(again['messages'],messages);self.assertEqual(again['settings'],settings)
   with self.assertRaises(HistoryError):store.save({'id':None,'revision':0,'messages':[{**messages[0],'voice_profile':'angry'}],'settings':settings})
if __name__=='__main__':unittest.main()
