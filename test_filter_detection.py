"""Compatibility with two- and three-column FFmpeg filter listings."""
import subprocess
import unittest
from unittest.mock import patch
import hdr
import subtitles


class FilterDetection(unittest.TestCase):
    def tearDown(self):
        hdr.capabilities.cache_clear()
        subtitles.capabilities.cache_clear()

    def listing(self, flags, missing=()):
        names=('zscale','tonemap','sidedata','format','setparams','libplacebo','subtitles','overlay','scale2ref')
        return 'Filters:\n  T.. = Timeline support\n  .S. = Slice threading\n'+''.join(
            f' {flags} {name:18} V->V       Example filter.\n' for name in names if name not in missing)

    def response(self, listing, stderr=False):
        def run(args, **kwargs):
            if '-filters' in args:
                return subprocess.CompletedProcess(args, 0, '' if stderr else listing, listing if stderr else '')
            return subprocess.CompletedProcess(args, 0, 'apply_dolbyvision\n  DOVI_METADATA 42\n', '')
        return run

    def test_both_formats_and_output_streams(self):
        for flags in ('..','TS','T.','.S','...','TSC','.S.'):
            for stderr in (False,True):
                with self.subTest(flags=flags,stderr=stderr), patch('subprocess.run',side_effect=self.response(self.listing(flags),stderr)):
                    hdr.capabilities.cache_clear();subtitles.capabilities.cache_clear()
                    cap=hdr.capabilities()
                    self.assertTrue(cap['cpu']);self.assertTrue(cap['libplacebo']);self.assertTrue(cap['dolbyVision'])
                    self.assertNotIn('=',cap['filters'])
                    self.assertTrue(subtitles.capabilities()['textBurn']);self.assertTrue(subtitles.capabilities()['bitmapBurn'])

    def test_missing_filter_is_reported_accurately(self):
        with patch('subprocess.run',side_effect=self.response(self.listing('..',('zscale',)))):
            hdr.capabilities.cache_clear()
            self.assertFalse(hdr.capabilities()['cpu'])
            with self.assertRaisesRegex(ValueError,'Missing FFmpeg filters: zscale\\.'):
                hdr.validate({'hdrTarget':'sdr','video':'libx264'})

    def test_process_failure_is_not_an_empty_filter_list(self):
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1,'','FFmpeg loading failed')):
            for module in (hdr,subtitles):
                with self.assertRaisesRegex(ValueError,'Could not query FFmpeg filters: FFmpeg loading failed'):
                    module.capabilities()

if __name__=='__main__': unittest.main()
