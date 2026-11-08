"""Test without downloading PellaV2 or accessing GitHub/LiveKit."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'voice_detector'))
from v3_common import label_to_int, read_manifest, metrics, window_starts, WINDOW, read_scores, write_csv, FIELDS
from simulate_telephony import narrowband,noise_at_snr
from calibrate_detector import platt_fit,apply_calibration,pick_threshold,wilson_upper


class TestV3(unittest.TestCase):
    def test_auc_perfect_and_false_alarm(self):
        rows=[{'label':'real','score':0.1},{'label':'real','score':0.2},
              {'label':'fake','score':0.8},{'label':'fake','score':0.9}]
        got=metrics(rows,0.5)
        self.assertEqual(got['roc_auc'],1.)
        self.assertEqual(got['fake_recall'],1.)
        self.assertEqual(got['real_false_positive_rate'],0.)
        self.assertAlmostEqual(got['accuracy'],1.)

    def test_auc_ties(self):
        self.assertAlmostEqual(metrics([{'label':'real','score':.5},{'label':'fake','score':.5}])['roc_auc'],.5)

    def test_windows_no_padding_and_bounded(self):
        self.assertEqual(window_starts(WINDOW-1),[])
        self.assertEqual(window_starts(WINDOW),[0])
        self.assertLessEqual(len(window_starts(WINDOW*100,max_windows=12)),12)

    def test_calibration_monotonic(self):
        scores=np.array([.02,.15,.2,.3,.7,.8,.85,.92]); y=np.array([0,0,0,0,1,1,1,1])
        params=platt_fit(scores,y)
        probs=apply_calibration(scores,params)
        self.assertTrue(np.all(np.diff(probs)>=0))
        self.assertTrue(all(0<=x<=1 for x in probs))

    def test_fpr_bound_rejects_small_validation(self):
        y=np.array([0]*10+[1]*10)
        p=np.array([.05]*10+[.95]*10)
        self.assertIsNone(pick_threshold(p,y,target_fpr=.05))
        self.assertGreater(wilson_upper(0,10),.05)

    def test_narrowband_noise_shape_and_seed(self):
        x=(np.sin(np.arange(64000)*2*np.pi*440/16000)*.03).astype('float32')
        self.assertTrue(np.isfinite(narrowband(x)).all())
        self.assertEqual(len(narrowband(x)),len(x))
        self.assertTrue(np.allclose(noise_at_snr(x,99),noise_at_snr(x,99)))

    def test_split_leakage_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            x=np.zeros(64000,dtype='float32')
            sf.write(root/'clip.wav',x,16000)
            entries=[{'sample_id':'one','path':'clip.wav','label':'real','split':'val','source_id':'same','speaker_id':'a'},
                     {'sample_id':'two','path':'clip.wav','label':'fake','split':'test','source_id':'same','speaker_id':'b'}]
            write_csv(root/'manifest.csv',entries,FIELDS)
            with self.assertRaisesRegex(ValueError,'leakage'):
                read_manifest(root/'manifest.csv')

    def test_manifest_and_score_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sf.write(root/'a.wav',np.zeros(64000),16000)
            rows=[{'sample_id':'x','path':'a.wav','label':'real','split':'test','source_id':'x', 'speaker_id':'x'}]
            write_csv(root/'manifest.csv',rows,FIELDS)
            loaded=read_manifest(root/'manifest.csv')
            self.assertEqual(loaded[0]['label'],'real')
            rows=[{'sample_id':'x','label':'real','split':'test','score':.2}]
            write_csv(root/'scores.csv',rows,['sample_id','label','split','score'])
            self.assertEqual(read_scores(root/'scores.csv','test')[0]['score'],.2)
            with self.assertRaises(FileExistsError): write_csv(root/'scores.csv',rows,['sample_id'])

    def test_mock_streaming_fast(self):
        cmd=[sys.executable,str(ROOT/'voice_detector'/'benchmark_streaming.py'),
             '--mode','mock','--duration','5','--speed','100','--mock-delay','.002']
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        result=json.loads(p.stdout)
        self.assertEqual(result['mode'],'mock')
        self.assertGreaterEqual(result['analyzed_windows'],1)
        self.assertGreaterEqual(result['audio_samples_received'],64000)

if __name__=='__main__':unittest.main()
