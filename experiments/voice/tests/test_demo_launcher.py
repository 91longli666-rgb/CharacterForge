"""Regression for whole-Demo stop confirmation; no real service is stopped."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch,MagicMock

script=Path(__file__).resolve().parents[3]/'scripts/demo.py'
spec=importlib.util.spec_from_file_location('demo_launcher_test',script)
demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)


class LauncherTests(unittest.TestCase):
    def test_stop_waits_for_last_asr_port(self):
        calls=[]
        def connect(address,timeout):
            calls.append(address[1])
            if len(calls)==3:return MagicMock()  # ASR still acknowledges closing.
            raise ConnectionRefusedError()
        with patch.object(demo,'status',return_value={'app':'Cartman3B-Test'}),patch.object(demo,'post',return_value={'ok':True}) as post,patch.object(demo.socket,'create_connection',side_effect=connect),patch.object(demo.time,'sleep'):
            result=demo.stop()
        self.assertEqual(calls,[7862,7864,7865]*2)
        self.assertEqual(result['closed_ports'],[7862,7864,7865]);post.assert_called_once_with('/api/shutdown')
    def test_unrelated_listener_is_never_stopped(self):
        with patch.object(demo,'status',side_effect=RuntimeError('Other app')),patch.object(demo,'post') as post:
            with self.assertRaises(RuntimeError):demo.stop()
            post.assert_not_called()
    def test_old_app_does_not_receive_demo_start(self):
        with patch.object(demo,'status',return_value={'app':'Cartman3B-Test'}),patch.object(demo,'post') as post:
            with self.assertRaises(RuntimeError):demo.start(no_browser=True)
            post.assert_not_called()


if __name__=='__main__':unittest.main()
