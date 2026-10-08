"""Geometry invariants for automatic crops; no model downloads or GPU needed."""
import unittest
from run_auto_layout import make_regions

def d(i,label,box): return dict(index=i,label=label,bbox=box,score=.9)

class RegionTests(unittest.TestCase):
    def test_table_blocks_text_merge_and_all_content_ids_survive(self):
        ds=[d(0,'text',[0,0,90,20]),d(1,'table',[0,24,90,70]),d(2,'text',[0,74,90,90])]
        regions,omitted,fallback=make_regions(ds,100,2000)
        self.assertEqual(len(regions),3)
        self.assertEqual(sorted(i for r in regions for i in r['detection_ids']),[0,1,2])
        self.assertFalse(omitted or fallback)

    def test_adjacent_header_fragments_merge_and_padding_stays_inside(self):
        regions,_,_=make_regions([d(0,'text',[0,0,40,15]),d(1,'text',[44,0,99,15])],100,100)
        self.assertEqual(len(regions),1)
        self.assertEqual(regions[0]['bbox'],[0,0,100,19])

    def test_image_only_returns_explicit_full_page_fallback(self):
        regions,omitted,fallback=make_regions([d(0,'image',[5,5,95,95])],100,100)
        self.assertTrue(fallback)
        self.assertEqual(regions[0]['bbox'],[0,0,100,100])
        self.assertEqual(len(omitted),1)

if __name__=='__main__': unittest.main()
