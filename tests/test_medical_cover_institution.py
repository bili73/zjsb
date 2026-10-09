"""The known cover row is source evidence; a logo or filename is not."""
import unittest
from test_hr_medical_profile import block
from ocr_app.extraction import extract_result

NAME='普潓年华健康体检中心（西安未央体检中心）'
def cover(text=NAME+'(11572)',page=1,box=(.4,.64,.84,.67)):
    value=block(text,page=page);value['bbox']=list(box);return value
def institution(*evidence):
    return extract_result(list(evidence),'MEDICAL_REPORT')['basic_info']['institution']

class MedicalCoverInstitutionTests(unittest.TestCase):
    def test_branch_name_excludes_code_but_raw_source_keeps_it(self):
        source=cover();field=institution(source)
        self.assertEqual(field['value'],NAME)
        self.assertEqual(field['source']['raw_text'],source['text'])
        self.assertEqual(field['source']['bbox'],source['bbox'])

    def test_actual_prefix_is_preserved_not_rewritten(self):
        text=NAME.replace('普潓','普惠')
        self.assertEqual(institution(cover(text))['value'],text)

    def test_wrong_page_logo_position_and_whole_page_ocr_abstain(self):
        for source in [cover(page=2),cover(box=(.05,.02,.45,.08)),cover(box=(0,0,1,1))]:
            with self.subTest(source=source):self.assertIsNone(institution(source)['value'])

    def test_unknown_or_incomplete_name_is_not_guessed(self):
        for text in ['其他医院（某分院）','普潓年华健康体检中心','普潓年华健康体检中心（分店不清楚','工作单位：普潓年华健康体检中心（西安未央体检中心）']:
            with self.subTest(text=text):self.assertIsNone(institution(cover(text))['value'])

    def test_different_eligible_branches_conflict_not_choose_last(self):
        field=institution(cover(),cover(NAME.replace('未央','高新')))
        self.assertIsNone(field['value']);self.assertEqual(field['review_reason'],'CONFLICT')

    def test_existing_explicit_field_remains_supported(self):
        self.assertEqual(institution(block('体检机构：明确标注的医院'))['value'],'明确标注的医院')

if __name__=='__main__':unittest.main()
