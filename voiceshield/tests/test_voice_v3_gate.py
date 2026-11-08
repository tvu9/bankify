import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'voice_detector'))
from gate_model_upgrade import evaluate_candidate


class ModelGateTests(unittest.TestCase):
    def make(self,ls,fs):
        rows=[]
        for i,p in enumerate(ls): rows.append({'sample_id':f'real{i}', 'source_id':f'R{i}', 'label':'real','score':p})
        for i,p in enumerate(fs): rows.append({'sample_id':f'fake{i}', 'source_id':f'F{i}', 'label':'fake','score':p})
        return rows

    def test_fails_on_accuracy_regression_even_when_faster(self):
        a=self.make([.1,.2],[.7,.9])
        b=self.make([.9,.2],[.7,.9])
        result=evaluate_candidate(a,b,1000,500,min_clips=4)
        self.assertFalse(result['release_candidate_passes_screen'])
        self.assertFalse(result['checks']['false_positive_rate_not_higher'])

    def test_fails_on_latency_regression(self):
        a=self.make([.1,.3],[.4,.9])
        b=self.make([.1,.2],[.9,.99])
        result=evaluate_candidate(a,b,1000,1500,min_clips=4)
        self.assertFalse(result['release_candidate_passes_screen'])
        self.assertFalse(result['checks']['cpu_p95_at_least_5pct_faster'])

    def test_reject_mismatched_ids(self):
        a=self.make([.1,.2],[.7,.9])
        b=self.make([.1,.2],[.7,.9]); b[0]['source_id']='different'
        with self.assertRaises(ValueError): evaluate_candidate(a,b,1000,500,min_clips=4)

if __name__=='__main__':unittest.main()
