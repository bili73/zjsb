"""Updated date semantics keep old references and unknowns distinct."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from probe_diploma_accuracy import reference_for
from probe_current_pipeline import ProbeError
from schema_extraction import score

class DiplomaAccuracyProtocolTests(unittest.TestCase):
    def test_new_semantics_do_not_mutate_old_reference_or_invent_day(self):
        fields=[dict(key='graduate_date',required=True)];old={'graduate_date':dict(status='uncertain',value=None),'principal':dict(status='uncertain',value=None)}
        before=copy.deepcopy(old);new=reference_for(fields,old,{'graduate_date':dict(status='present',value='2025-06')})
        self.assertEqual(old,before);self.assertNotIn('principal',new)
        self.assertEqual(score(new,{'graduate_date':'2025-06-01'},fields)[0]['outcome'],'wrong')
        self.assertEqual(score(new,{},fields)[0]['outcome'],'missing')

    def test_incomplete_unknown_or_empty_present_references_are_rejected(self):
        fields=[dict(key='school_name',required=True)]
        for overrides in [{},{'principal':dict(status='uncertain')},{'school_name':dict(status='present',value='')}]:
            with self.subTest(overrides=overrides),self.assertRaises(ProbeError):reference_for(fields,{},overrides)

if __name__=='__main__':unittest.main()
