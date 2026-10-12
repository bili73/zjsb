"""Validate actual extraction/review payloads and public mutation contracts."""
import copy
from pathlib import Path
import sys
import unittest
from uuid import uuid4

import jsonschema
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from test_pipeline_schema import json_schema
from ocr_app.doc_profiles import catalogue
from ocr_app.extraction import extract_result
from ocr_app.review import apply_review
from ocr_app.task_store import public_result
from ocr_app.routes import FullPreview, ExportBody


class DocumentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document=json_schema(yaml.safe_load((ROOT/'openapi.yaml').read_text(encoding='utf-8')))

    def validate(self,name,value):
        jsonschema.Draft7Validator(dict(self.document,**{'$ref':'#/components/schemas/'+name}),format_checker=jsonschema.FormatChecker()).validate(value)

    def test_upload_limit_contract_matches_admission(self):
        from ocr_app.upload_limits import MAX_FILES, MAX_FILE_BYTES, MAX_BATCH_BYTES
        self.assertEqual((MAX_FILES, MAX_FILE_BYTES, MAX_BATCH_BYTES),
                         (100, 50 * 1024 * 1024, 500 * 1024 * 1024))
        upload = self.document['paths']['/batches']['post']
        files = upload['requestBody']['content']['multipart/form-data']['schema']['properties']['files']
        self.assertEqual((files['minItems'], files['maxItems']), (1, MAX_FILES))
        self.assertIn('50MB', files['items']['description'])
        self.assertIn('500MB', files['items']['description'])
        self.assertIn('413', upload['responses'])
        self.assertIn('FILE_TOO_LARGE/413', upload['description'])

    def test_account_owner_and_name_update_contracts(self):
        owner = dict(user_id=str(uuid4()), username='alice', display_name='合成姓名', account_exists=True)
        self.validate('BatchOwner', owner)
        self.validate('BatchOwner', dict(user_id=None, username=None, display_name=None, account_exists=False))
        for extra in [dict(account_exists='yes'), dict(username='invalid name'), dict(display_name=''), dict(secret='no'), dict(user_id=None), dict(username=None)]:
            with self.assertRaises(jsonschema.ValidationError):
                self.validate('BatchOwner', dict(owner, **extra))
        for body in [dict(display_name='新姓名'), dict(enabled=False)]:
            self.validate('UpdateUserRequest', body)
        for body in [{}, dict(display_name=' '), dict(display_name=4), dict(display_name='新姓名', enabled=True), dict(role='admin')]:
            with self.assertRaises(jsonschema.ValidationError):
                self.validate('UpdateUserRequest', body)

    def test_measured_progress_allows_unknown_and_zero_totals_without_fake_estimates(self):
        detail = dict(stage='OCR', prepared_pages=1, total_pages=2, processed_regions=0,
                      recognized_regions=0, incomplete_regions=0, total_regions=None)
        self.validate('TaskProgressDetail', detail)
        self.validate('TaskProgressDetail', dict(detail, total_pages=None))
        self.validate('TaskProgressDetail', dict(detail, stage='EXTRACTING', total_regions=0))
        self.assertTrue(self.document['components']['schemas']['Task']['properties']['progress']['deprecated'])
        for extra in [dict(total_regions=-1), dict(processed_regions=0.5), dict(total_pages=0),
                      dict(stage='GENERATING'), dict(eta_seconds=42)]:
            with self.subTest(extra=extra), self.assertRaises(jsonschema.ValidationError):
                self.validate('TaskProgressDetail', dict(detail, **extra))

    def envelope(self,result):
        return dict(result,task_id=str(uuid4()),run_id=str(uuid4()),result_revision=1,status=result.get('status','NEED_REVIEW'))

    def test_actual_catalogue_plain_array_and_all_types(self):
        schema=self.document['paths']['/doc-types']['get']['responses']['200']['content']['application/json']['schema']
        jsonschema.Draft7Validator(dict(self.document,**schema)).validate(catalogue())
        for entry in catalogue():
            with self.subTest(doc_type=entry['doc_type']):
                result=extract_result([dict(text='字段：合成内容',page=1,region_id=str(uuid4()),bbox=[0,0,1,1],extraction_method='pdf_text')],entry['doc_type'])
                self.validate('TaskResult',self.envelope(public_result(result)))

    def test_shared_required_settings_contract(self):
        from ocr_app.required_fields import configuration, project_requirements
        self.validate('RequiredFieldSettings', configuration(dict(revision=0, overrides={})))
        policy = dict(revision=2, overrides={'DIPLOMA':['duration'], 'HOUSEHOLD_REGISTER':['members.gender'], 'GENERIC':[]})
        self.validate('RequiredFieldSettings', configuration(policy))
        for selected in [[], ['duration'], None]:
            self.validate('RequiredFieldSave', dict(doc_type='DIPLOMA', required_fields=selected, expected_revision=2))
        for extra in [dict(required_fields=['name','name']), dict(expected_revision=-1), dict(extra=True)]:
            with self.assertRaises(jsonschema.ValidationError):
                self.validate('RequiredFieldSave', dict(dict(doc_type='DIPLOMA',required_fields=[],expected_revision=2),**extra))
        result = project_requirements(extract_result([], 'DIPLOMA'), policy['overrides'])
        self.validate('TaskResult', self.envelope(dict(result,required_fields_revision=2)))

    def test_real_human_medical_shapes_and_readonly_rejection(self):
        result=extract_result([dict(text='<table><tr><th>项目名称</th><th>检测结果</th><th>风险等级</th></tr><tr><td>合成项目</td><td>2</td><td>A</td></tr></table>',page=1,region_id=str(uuid4()),extraction_method='pdf_text')],'MEDICAL_REPORT')
        result['pages']=[dict(page_id=str(uuid4()),page_index=1,width=100,height=100,extraction_method='pdf_text')]
        body=dict(run_id=str(uuid4()),expected_revision=0,fields={'name':'合成姓名','gender':'男','exam_projects':'眼科常规；内科检查','exam_date':'2026-10-08'},items=[dict(item_id=result['items'][0]['item_id'],risk_grade='B',diagnosis='报告原有诊断')],coverage=dict(pages=[1],reason='逐页核对完成',regions=[]),report_summary=dict(source_page=1,reason='人工核对清单',title='您共有1项异常需进一步检查并治疗：',scope='follow_up_required',declared_count=1,added_findings=[dict(text='原报告条目',risk_grade='B',diagnosis='报告原有诊断',result_item_id=result['items'][0]['item_id'])]))
        self.validate('ReviewRequest',body)
        reviewed=apply_review(result,body,actor='operator-test',coverage_verified=True)
        self.assertEqual(reviewed['basic_info']['gender']['value'],'M')
        self.validate('TaskResult',self.envelope(public_result(reviewed)))
        bad=copy.deepcopy(body);bad['items'][0]['abnormal_flag']='NORMAL'
        with self.assertRaises(jsonschema.ValidationError):self.validate('ReviewRequest',bad)

    def test_export_request_selection_and_versions(self):
        task,run=str(uuid4()),str(uuid4())
        request=dict(task_ids=[task],versions=[dict(task_id=task,run_id=run,result_revision=2)],masked=True,format='xlsx')
        self.validate('ExportRequest',request)
        for legacy in [dict(request,masked=False),dict(request,masked=False,reason=''),dict(request,masked=True,reason=None)]:
            self.validate('ExportRequest',legacy)
            ExportBody.model_validate(legacy)
        for bad in [dict(request,batch_id=str(uuid4())),dict(request,format='csv'),dict(request,reason='x'*1001),dict(request,extra=True)]:
            with self.assertRaises(jsonschema.ValidationError):self.validate('ExportRequest',bad)

    def test_preview_reveal_and_generic_member_requests(self):
        version=dict(run_id=str(uuid4()),expected_revision=0)
        for extra in [{},{'reason':''},{'reason':None},{'reason':'核对来源'}]:
            request=dict(version,page=1,**extra)
            self.validate('FullPreviewRequest',request)
            FullPreview.model_validate(request)
        self.validate('RevealRequest',dict(version,fields=['passport_number','online_verification_code'],reason='核对字段'))
        with self.assertRaises(jsonschema.ValidationError):self.validate('RevealRequest',dict(version,fields=['cvv'],reason='核对字段'))
        self.validate('ReviewRequest',dict(version,members=[dict(index=0,fields={'name':'合成姓名'},absence_reasons={'occupation':'NOT_ON_DOCUMENT'})]))
        self.validate('ReviewRequest',dict(version,generic=dict(full_text='确认正文',key_values=[dict(key='合成键',value='合成值')])) )

    def test_authenticated_projection_preserves_full_business_values(self):
        # Synthetic values exercise actual public projection, not the retired
        # masking utility. Private review history remains private.
        for doc_type,key,value in [('PASSPORT','passport_number','E12345678'),('BANK_CARD','card_number','6222021234567890123'),('HOUSEHOLD_REGISTER','household_no','001234'),('XUEXIN_DIPLOMA_TABLE','online_verification_code','AB12CD34EF56GH78')]:
            with self.subTest(doc_type=doc_type):
                result=extract_result([],doc_type)
                field=next(field for field in result['fields'] if field['key']==key)
                field['value']=value
                field['_sensitive_history']=['old-private-value']
                field['source']={'page':1,'raw_text':value}
                projected=public_result(result)
                actual=next(field for field in projected['fields'] if field['key']==key)
                self.assertEqual(actual['value'],value)
                self.assertEqual(actual['source']['raw_text'],value)
                self.assertNotIn('_sensitive_history',actual)
                self.validate('TaskResult',self.envelope(projected))

    def test_full_preview_legacy_flag_contract_keeps_version_binding(self):
        preview=self.document['paths']['/tasks/{task_id}/preview']['get']
        params={p['name']:p for p in preview['parameters']}
        self.assertTrue(params['run_id']['required'])
        self.assertTrue(params['result_revision']['required'])
        self.assertTrue(params['masked']['deprecated'])
        self.assertNotIn('enum',params['masked']['schema'])
        self.assertIn('image/png',preview['responses']['200']['content'])
        self.assertIn('X-Result-Revision',preview['responses']['200']['headers'])
        self.assertTrue(self.document['components']['schemas']['Field']['properties']['value_masked']['deprecated'])

    def test_confirmation_reason_is_optional_but_not_arbitrary(self):
        version=dict(run_id=str(uuid4()),expected_revision=0)
        issue_id=str(uuid4())
        for accepted in [dict(issue_id=issue_id),dict(issue_id=issue_id,reason=''),dict(issue_id=issue_id,reason='人工核对')]:
            self.validate('ReviewRequest',dict(version,accepted_issues=[accepted]))
        for accepted in [dict(issue_id=issue_id,reason=None),dict(issue_id=issue_id,reason='x'*1001),dict(issue_id=issue_id,extra=True)]:
            with self.assertRaises(jsonschema.ValidationError):
                self.validate('ReviewRequest',dict(version,accepted_issues=[accepted]))

    def test_bank_derived_fields_validate_and_do_not_claim_ocr_source(self):
        result=extract_result([dict(text='6222021234567890123',page=1,region_id=str(uuid4()),bbox=[0,0,1,1],extraction_method='ocr')],'BANK_CARD')
        self.validate('TaskResult',self.envelope(public_result(result)))
        derived=[f for f in result['fields'] if f.get('value_origin')=='derived']
        self.assertEqual({f['key'] for f in derived},{'bin_code','bank_name','card_type'})
        for field in derived:
            self.assertNotIn('source',field)
            self.validate('FieldDerivation',field['derivation'])
        bad=copy.deepcopy(derived[0]['derivation']);bad['matched_prefix']='123456789'
        with self.assertRaises(jsonschema.ValidationError):self.validate('FieldDerivation',bad)

    def test_implemented_methods_and_explicit_future_paths(self):
        self.assertEqual(self.document['info']['version'],'1.22.0')
        self.assertIn('post',self.document['paths']['/export'])
        self.assertNotIn('get',self.document['paths']['/export'])
        permissions=self.document['paths']['/auth/me']['get']['responses']['200']['content']['application/json']['schema']['properties']['permissions']['items']['enum']
        self.assertEqual(set(permissions),{'review','reveal','rerun','export'})
        self.assertIn('operator/admin',self.document['paths']['/export']['post']['description'])
        self.assertIn('viewer返回403',self.document['paths']['/tasks/{task_id}/preview']['get']['description'])
        self.assertIn('post',self.document['paths']['/tasks/{task_id}/preview'])
        self.assertFalse(self.document['paths']['/tasks/{task_id}/reject']['post']['x-implemented'])
        self.assertFalse(self.document['components']['schemas']['MedicalItem']['additionalProperties'])
        for code in ['CARD_ADMISSION_FAILED','UNSAFE_CARD_INPUT','EXPORT_BLOCKED','EXPORT_VALUE_TOO_LONG','PREVIEW_MASK_UNAVAILABLE']:
            self.validate('Error',dict(code=code,message='安全提示',details={'tasks':[]}))

    def test_person_package_append_contract_is_implemented_and_versioned(self):
        operation = self.document['paths']['/batches/{batch_id}/append']['post']
        self.assertTrue(operation['x-implemented'])
        request = operation['requestBody']['content']['multipart/form-data']['schema']
        self.assertEqual(set(request['required']), {'files', 'expected_revision'})
        self.assertEqual(request['oneOf'], [{'required': ['doc_type_hint']}, {'required': ['file_types']}])
        self.assertEqual(request['properties']['file_types']['maxLength'], 4096)
        validator = jsonschema.Draft7Validator(dict(self.document, **request))
        common = dict(files=['synthetic.png'], expected_revision=0)
        validator.validate(dict(common, doc_type_hint='DIPLOMA'))
        validator.validate(dict(common, file_types='["DIPLOMA"]'))
        for invalid in [common, dict(common, file_types='["DIPLOMA"]', doc_type_hint='DIPLOMA')]:
            with self.assertRaises(jsonschema.ValidationError): validator.validate(invalid)
        self.assertNotIn('person_name', request['properties'])
        for status in ['202', '401', '403', '404', '409', '413', '415', '422']:
            self.assertIn(status, operation['responses'])
        self.validate('Batch', dict(batch_id=str(uuid4()), person_name='合成人员', package_revision=0,
                                   id_card_pairing='missing_back', warnings=[dict(code='MISSING_ID_BACK', message='缺少国徽面')]))

    def test_mixed_creation_and_classification_contracts(self):
        request = self.document['paths']['/batches']['post']['requestBody']['content']['multipart/form-data']['schema']
        validator = jsonschema.Draft7Validator(dict(self.document, **request))
        validator.validate(dict(files=['synthetic.png'], person_name='合成人员', file_types='["DIPLOMA"]'))
        validator.validate(dict(files=['synthetic.png'], file_types='["DIPLOMA"]'))
        operation = self.document['paths']['/classify']['post']
        schema = operation['requestBody']['content']['multipart/form-data']['schema']
        self.assertEqual(schema['properties']['files']['maxItems'], 1)
        response = operation['responses']['200']['content']['application/json']['schema']
        jsonschema.Draft7Validator(dict(self.document, **response)).validate(
            dict(doc_type=None, basis='unknown', reason='请选择', candidates=[]))

    def test_batch_deletion_contract_is_implemented_and_version_bound(self):
        from ocr_app.routes import DeleteBatchBody
        request = dict(versions=[dict(task_id=str(uuid4()), run_id=str(uuid4()), expected_revision=1)])
        self.validate('BatchDeleteRequest', request)
        self.assertEqual(DeleteBatchBody.model_validate(request).model_dump(mode='json'), request)
        self.validate('BatchDeleteResponse', dict(batch_id=str(uuid4()), task_ids=[request['versions'][0]['task_id']], cleanup_pending=False))
        operation = self.document['paths']['/batches/{batch_id}']['delete']
        self.assertNotEqual(operation.get('x-implemented'), False)
        self.assertIn('200', operation['responses'])
        self.assertNotIn('204', operation['responses'])
        for invalid in [dict(versions=[]), dict(versions=[dict(request['versions'][0], extra='x')])]:
            with self.assertRaises(jsonschema.ValidationError): self.validate('BatchDeleteRequest', invalid)

    def test_person_name_confirmation_contract(self):
        from ocr_app.routes import PersonBody
        request = dict(person_name='合成姓名', expected_revision=0)
        self.validate('PersonNameRequest', request)
        self.assertEqual(PersonBody.model_validate(request).model_dump(), request)
        self.validate('Batch', dict(batch_id=str(uuid4()), is_person_package=True, person_name=None,
            package_revision=0, id_card_pairing='not_provided', name_suggestions=[dict(name='合成姓名', sources=[
                dict(task_id=str(uuid4()), doc_type='DIPLOMA', file_name='synthetic.png')])]))
        operation = self.document['paths']['/batches/{batch_id}/person']['patch']
        for code in ['200', '401', '403', '404', '409', '422']:
            self.assertIn(code, operation['responses'])

    def test_human_added_household_member_matches_contract(self):
        result=extract_result([], 'HOUSEHOLD_REGISTER')
        result['pages']=[dict(page_id=str(uuid4()),page_index=1,width=100,height=100,extraction_method='pending')]
        request=dict(run_id=str(uuid4()),expected_revision=1,fields={'household_type':'集体户口','household_no':'001234','address':'合成地址'},added_members=[dict(source_page=1,fields={'name':'合成成员','gender':'M'})],coverage=dict(pages=[1],reason='人工核对完整页',regions=[dict(region_id=str(uuid4()),action='TRANSCRIBED',reason='登记卡补录',added_member_indexes=[0])]))
        self.validate('ReviewRequest',request)
        reviewed=apply_review(result,request,actor='operator-test',coverage_verified=True)
        self.validate('TaskResult',self.envelope(public_result(reviewed)))
        self.assertEqual(reviewed['members'][0]['source_page'],1)
        bad=copy.deepcopy(request);bad['added_members'][0]['member_id']=str(uuid4())
        with self.assertRaises(jsonschema.ValidationError):self.validate('ReviewRequest',bad)


if __name__=='__main__':unittest.main()
