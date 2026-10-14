import copy
import io
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from PIL import Image, ImageDraw
import fitz
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_result
from ocr_app.pipeline import process_document
from ocr_app.review import apply_review
from ocr_app.exporting import workbook_bytes
from ocr_app.task_store import TaskError
from ocr_app.generic_layout import plan_form_regions


def block(text, page=1, bbox=None, **extra):
    return dict(text=text, page=page, region_id=str(uuid4()), bbox=bbox or [0,0,1,1],
                extraction_method='ocr', **extra)


def generic(*blocks):
    return extract_result(list(blocks), 'GENERIC')['generic']


class GenericFormTests(unittest.TestCase):
    def test_multiple_colon_pairs_and_missing_values_preserve_repeats_and_sources(self):
        b=block('姓名：张三  部门：研发部\n姓名：李四  电话：\n到岗日期：2026年10月14日')
        g=generic(b)
        self.assertEqual([(p['key'],p['value']) for p in g['key_values']],
                         [('姓名','张三'),('部门','研发部'),('姓名','李四'),('电话',None),('到岗日期','2026年10月14日')])
        self.assertEqual(len({p['pair_id'] for p in g['key_values']}),5)
        for pair in g['key_values']:
            self.assertEqual(pair['source']['region_id'],b['region_id']);self.assertIsNone(pair['confidence'])

    def test_merged_form_and_header_over_value_keep_table_and_multiline_text(self):
        b=block('<table><tr><td>姓名：</td><td>张三</td><td>部门：</td><td>研发部</td></tr>'
                '<tr><td>申请原因：</td><td colspan="3">第一行<br>第二行</td></tr></table>')
        g=generic(b)
        self.assertEqual([(p['key'],p['value']) for p in g['key_values']],
                         [('姓名','张三'),('部门','研发部'),('申请原因','第一行\n第二行')])
        self.assertEqual(len(g['tables']),1);self.assertIn('第二行',g['full_text'])
        above=generic(block('<table><tr><th>姓名</th><th>部门</th></tr><tr><td>张三</td><td>研发部</td></tr></table>'))
        self.assertEqual([(p['key'],p['value']) for p in above['key_values']],[('姓名','张三'),('部门','研发部')])

    def test_record_tables_and_ambiguous_text_are_preserved_without_invented_pairs(self):
        text='<table><tr><th>名称</th><th>数量</th></tr><tr><td>甲</td><td>1</td></tr><tr><td>乙</td><td>2</td></tr></table>'
        g=generic(block(text),block('这是一段说明文字，不是字段。'))
        self.assertEqual(g['key_values'],[]);self.assertEqual(g['tables'][0]['rows'][2],['乙','2'])
        self.assertIn('这是一段说明文字',g['full_text'])

    def test_native_overlap_deduplicates_only_same_source_area(self):
        table=block('<table><tr><td>姓名：</td><td>张三</td></tr></table>',bbox=[.1,.1,.8,.3],
                    table_rows=[dict(cell_bboxes=[[.1,.1,.3,.3],[.3,.1,.8,.3]])])
        table['extraction_method']='pdf_text'
        duplicate=block('姓名：张三',bbox=[.1,.1,.8,.3]);duplicate['extraction_method']='pdf_text'
        elsewhere=block('姓名：张三',bbox=[.1,.6,.8,.8]);elsewhere['extraction_method']='pdf_text'
        g=generic(duplicate,table,elsewhere)
        self.assertEqual(len(g['key_values']),2)
        self.assertEqual(g['key_values'][0]['source']['bbox_kind'],'cell')

    def test_native_table_must_contain_text_before_duplicate_is_removed(self):
        table=block('<table><tr><td>姓名：</td><td>张三</td></tr></table>')
        table['extraction_method']='pdf_text'
        extra=block('备注：请联系本人');extra['extraction_method']='pdf_text'
        g=generic(table,extra)
        self.assertIn('备注：请联系本人',g['full_text'])
        self.assertEqual(g['key_values'][-1]['value'],'请联系本人')

    def test_aligned_native_labels_and_ambiguous_neighbors(self):
        def native(text,box):
            b=block(text,bbox=box);b['extraction_method']='pdf_text';return b
        g=generic(native('姓名：',[.1,.1,.2,.13]),native('张三',[.22,.1,.3,.13]),
                  native('申请原因：',[.1,.3,.25,.33]),native('处理资料',[.1,.34,.4,.37]))
        self.assertEqual([(p['key'],p['value'],p['basis']) for p in g['key_values']],
                         [('姓名','张三','aligned_label'),('申请原因','处理资料','aligned_label')])
        g=generic(native('姓名：',[.1,.1,.2,.13]),native('张三',[.22,.1,.3,.13]),native('李四',[.32,.1,.4,.13]))
        self.assertIsNone(g['key_values'][0]['value'])

    def test_rowspan_label_keeps_all_corresponding_value_rows(self):
        g=generic(block('<table><tr><td rowspan="2">申请原因：</td><td>第一项</td></tr>'
                        '<tr><td>第二项</td></tr></table>'))
        self.assertEqual([(p['key'],p['value']) for p in g['key_values']],[('申请原因','第一项\n第二项')])

    def test_unpunctuated_form_and_ordinary_record_table(self):
        g=generic(block('<table><tr><td>姓名</td><td>张三</td></tr><tr><td>年龄</td><td>25</td></tr>'
                        '<tr><td>部门</td><td>产品开发部</td></tr></table>'))
        self.assertEqual(len(g['key_values']),3)
        records=generic(block('<table><tr><td>商品</td><td>数量</td></tr><tr><td>苹果</td><td>3</td></tr>'
                              '<tr><td>香蕉</td><td>2</td></tr></table>'))
        self.assertEqual(records['key_values'],[])

    def test_subject_bands_keep_notes_and_side_text_forces_whole_region(self):
        image=Image.new('RGB',(400,400),'white');draw=ImageDraw.Draw(image)
        for box in [(70,30,200,50),(20,100,380,300),(60,340,240,360)]:draw.rectangle(box,outline='black')
        lines=[dict(text='标题',box=[70,30,200,50]),dict(text='姓名：张三',box=[40,130,200,150]),dict(text='说明',box=[60,340,240,360])]
        with patch('ocr_app.generic_layout.locate_table_candidates',return_value=[dict(box=[20,100,380,300])]), \
             patch('ocr_app.generic_layout.nearby_text',return_value=lines):
            plans,_=plan_form_regions(image,(0,0,400,400),lambda:None)
        self.assertEqual([p['task'] for p in plans],['ocr','table','ocr'])
        self.assertEqual([line['text'] for p in plans for line in p['lines']],['标题','姓名：张三','说明'])
        lines.append(dict(text='旁注',box=[0,160,18,185]))
        with patch('ocr_app.generic_layout.locate_table_candidates',return_value=[dict(box=[20,100,380,300])]), \
             patch('ocr_app.generic_layout.nearby_text',return_value=lines):
            plans,_=plan_form_regions(image,(0,0,400,400),lambda:None)
        self.assertEqual(len(plans),1);self.assertEqual(plans[0]['task'],'ocr')

    def test_layout_failure_falls_back_but_deadline_is_not_hidden(self):
        image=Image.new('RGB',(100,100),'white')
        with patch('ocr_app.generic_layout.locate_table_candidates',side_effect=RuntimeError('detector unavailable')):
            plans,notes=plan_form_regions(image,(0,0,100,100),lambda:None)
            self.assertEqual(plans[0]['box'],(0,0,100,100));self.assertTrue(notes)
            with self.assertRaises(TimeoutError):plan_form_regions(image,(0,0,100,100),Mock(side_effect=TimeoutError()))

    def test_review_validates_pair_links_and_exports_every_saved_pair(self):
        original=extract_result([block('姓名：张三\n姓名：李四')],'GENERIC')
        pairs=original['generic']['key_values']
        body=dict(generic=dict(full_text='已修正正文',key_values=[dict(key='姓名',value='0001',source_pair_id=pairs[0]['pair_id']),
                                                              dict(key='姓名',value='=1+1')]))
        saved=apply_review(original,body,actor='human')
        self.assertEqual(saved['generic'],original['generic'])
        self.assertEqual(saved['reviewed_generic']['key_values'][0]['source_pair_id'],pairs[0]['pair_id'])
        sheet=load_workbook(io.BytesIO(workbook_bytes([dict(saved,task_id=str(uuid4()))])))['通用识别字段']
        self.assertIn('0001',[c.value for row in sheet for c in row])
        self.assertTrue(any(c.value=='=1+1' and c.data_type=='s' for row in sheet for c in row))
        bad=copy.deepcopy(body);bad['generic']['key_values'][0]['source_pair_id']=str(uuid4())
        with self.assertRaises(TaskError):apply_review(original,bad,actor='human')
        bad=copy.deepcopy(body);bad['generic']['key_values'][0]['source']={}
        with self.assertRaises(TaskError):apply_review(original,bad,actor='human')

    def test_generic_pipeline_uses_upright_paddle_then_bounded_glm(self):
        stream=io.BytesIO();Image.new('RGB',(300,200),'white').save(stream,format='PNG')
        recognize=Mock(side_effect=[dict(text='姓名：',termination_reason='token_limit'),dict(text='姓名：张三',termination_reason='eos')])
        attempts=[]
        with patch('ocr_app.image_preprocessing.prepare_image',side_effect=lambda image,check,**kw:(image,dict(rotation_degrees=0,deskew_degrees=0))) as upright, \
             patch('ocr_app.generic_layout.plan_form_regions',return_value=([dict(box=(0,0,300,200),task='ocr',lines=[])],[])):
            result=process_document(stream.getvalue(),'GENERIC',recognize=recognize,progress=Mock(),save_page=lambda *a:str(uuid4()),
                record_attempt=attempts.append,cancelled=lambda:False,deadline=time.monotonic()+180)
        self.assertEqual([c.args[0] for c in recognize.call_args_list],['paddleocr_vl','glm_ocr'])
        self.assertTrue(all(c.kwargs['generation_timeout_seconds']==40 for c in recognize.call_args_list))
        self.assertTrue(all(a['transform']=='original' for a in attempts))
        self.assertEqual(result['generic']['key_values'][0]['value'],'张三')
        upright.assert_called_once()
        self.assertEqual(upright.call_args.kwargs['doc_type'],'GENERIC')

    def test_native_pdf_reads_labels_without_loading_models(self):
        pdf=fitz.open();page=pdf.new_page()
        page.insert_text((70,80),'姓名：合成人员\n部门：产品开发部\n申请日期：2026年10月14日',fontname='china-s',fontsize=14)
        recognize=Mock(side_effect=AssertionError('Native text must not call a model'))
        result=process_document(pdf.tobytes(),'GENERIC',recognize=recognize,progress=Mock(),
            save_page=lambda *a:str(uuid4()),record_attempt=Mock(),cancelled=lambda:False,deadline=time.monotonic()+180)
        self.assertEqual(result['pages'][0]['extraction_method'],'pdf_text')
        self.assertEqual(result['generic']['key_values'][0]['value'],'合成人员')
        recognize.assert_not_called()

    def test_invalid_table_falls_back_and_deadline_keeps_partial_evidence(self):
        from ocr_app.documents import Page
        from ocr_app.pipeline import RecognitionFailure
        page=Page(1,Image.new('RGB',(300,200),'white'),ocr_boxes=[(0,0,300,200)])
        plans=([dict(box=(0,0,300,200),task='table',lines=[])],[])
        for predictions,expected_state in [
            ([dict(text='<table><tr><td>姓名：</td>',termination_reason='eos'),
              dict(text='<table><tr><td>姓名：</td><td>张三</td></tr></table>',termination_reason='eos')],'NEED_REVIEW'),
            ([dict(text='姓名：张三',termination_reason='token_limit'),RecognitionFailure('EXTRACT_TIMEOUT')],'FAILED')]:
            recognize=Mock(side_effect=predictions);attempts=[]
            with patch('ocr_app.pipeline.decode_pages',side_effect=lambda *a,**kw:iter([page])), \
                 patch('ocr_app.generic_layout.plan_form_regions',return_value=plans):
                result=process_document(b'%PDF-synthetic','GENERIC',recognize=recognize,progress=Mock(),
                    save_page=lambda *a:str(uuid4()),record_attempt=attempts.append,cancelled=lambda:False,deadline=time.monotonic()+180)
            self.assertEqual(result['status'],expected_state)
            self.assertEqual(result['generic']['key_values'][0]['value'],'张三')
            self.assertEqual(len(attempts),2)
            if expected_state=='FAILED':self.assertEqual(result['error']['code'],'EXTRACT_TIMEOUT')


if __name__=='__main__':unittest.main()
