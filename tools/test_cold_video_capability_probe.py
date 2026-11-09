#!/usr/bin/env python3
"""Exercise the cold-query probe with a process-local fake VT API, not hardware."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/video/vt_cold_capability_probe.m"


@unittest.skipUnless(sys.platform == "darwin", "requires Apple's Foundation/VideoToolbox headers")
class ColdCapabilityProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vt-cold-probe-test-")
        cls.root = Path(cls.temp.name)
        stub = cls.root / "vt_stub.c"
        stub.write_text(r'''
#include <VideoToolbox/VideoToolbox.h>
#include <stdlib.h>
Boolean VTIsHardwareDecodeSupported(CMVideoCodecType codec) {
    static unsigned calls;
    if (calls++ == 0) {
        if (codec != kCMVideoCodecType_H264) abort();
        const char *value = getenv("VT_PROBE_TEST_FIRST_H264");
        return value && value[0] == '1';
    }
    return 1;
}
''')
        cls.binary = cls.root / "probe"
        subprocess.run(["xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=15.0", "-fobjc-arc",
                        "-O2", "-Wall", "-Wextra", "-Werror", str(SOURCE), str(stub),
                        "-framework", "Foundation", "-framework", "CoreMedia", "-framework", "VideoToolbox",
                        "-o", str(cls.binary)], check=True, capture_output=True, text=True)
        driver = cls.root / "NVMTLDriver.bundle/Contents/MacOS/NVMTLDriver"
        driver.parent.mkdir(parents=True)
        marker = cls.root / "driver_marker.c"
        marker.write_text("void cold_probe_fixture_marker(void) {}\n")
        subprocess.run(["xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=15.0", "-dynamiclib",
                        str(marker), "-o", str(driver)], check=True, capture_output=True, text=True)
        cls.driver_marker = driver

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_probe(self, *args, first=False, loaded=False):
        env = {key: value for key, value in os.environ.items() if not key.startswith("DYLD_")}
        env["VT_PROBE_TEST_FIRST_H264"] = "1" if first else "0"
        if loaded:
            env["DYLD_INSERT_LIBRARIES"] = str(self.driver_marker)
        result = subprocess.run([str(self.binary), *args], env=env, capture_output=True, text=True, check=False)
        report = json.loads(result.stdout) if result.stdout else None
        return result, report

    def test_cold_binary_does_not_link_metal(self):
        libraries = subprocess.check_output(["otool", "-L", str(self.binary)], text=True)
        self.assertNotIn("/Metal.framework/", libraries)

    def test_first_query_is_h264_and_later_success_does_not_repair_it(self):
        result, report = self.run_probe("--require-first-h264")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["mode"], "cold")
        self.assertFalse(report["first_h264_hardware_supported"])
        self.assertTrue(report["h264_hardware_supported_after_other_queries"])
        self.assertTrue(report["hevc_hardware_supported"])
        self.assertTrue(report["vp9_hardware_supported"])
        self.assertFalse(report["hardware_playback_tested"])
        self.assertFalse(report["browser_sandbox_tested"])

    def test_supported_first_query_passes_the_requested_assertion(self):
        result, report = self.run_probe("--require-first-h264", first=True)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(report["first_h264_hardware_supported"])

    def test_report_only_does_not_assert_unsupported_or_opted_out_hardware(self):
        result, report = self.run_probe()
        self.assertEqual(result.returncode, 0)
        self.assertFalse(report["first_h264_hardware_supported"])

    def test_preloaded_driver_invalidates_a_cold_start_even_if_query_succeeds(self):
        result, report = self.run_probe("--require-first-h264", first=True, loaded=True)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(report["driver_loaded_before_first_query"])
        self.assertTrue(report["first_h264_hardware_supported"])

    def test_unknown_option_is_rejected(self):
        result, report = self.run_probe("--preload-plugin")
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(report)
        self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
