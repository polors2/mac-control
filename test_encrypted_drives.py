import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from drives import DriveManager

UUID='11111111-1111-4111-8111-111111111111'
SECRET='fixture-only-$pass-å'

class EncryptedDriveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'drives.json'
        self.state={'drives':[{'id':UUID,'name':'Example encrypted drive','model':'USB HDD','size':1000,'mounted':False,'encrypted':True,'locked':True,'state':'locked','volumes':[]}]}
        self.calls=[]
        def native(*args, password=None):
            self.calls.append((args,password))
            if args[0]=='unlock':
                if password!=SECRET:return {**copy.deepcopy(self.state),'error':'Check the password.','requiresPassword':True}
                self.state['drives'][0].update(mounted=True,locked=False,state='mounted')
            return copy.deepcopy(self.state)
        self.manager=DriveManager('unused',self.path,runner=native)
    def tearDown(self):self.temp.cleanup()

    def test_locked_volume_requests_password_without_attempting_mount(self):
        result=self.manager.set_mounted(UUID,True)
        self.assertTrue(result['requiresPassword']);self.assertTrue(result['error'])
        self.assertEqual(self.calls,[(('list',),None)])

    def test_unlock_success_saves_mount_choice_without_password(self):
        result=self.manager.set_mounted(UUID,True,password=SECRET)
        self.assertTrue(result['drives'][0]['mounted'])
        self.assertIn((('unlock',UUID),SECRET),self.calls)
        saved=self.path.read_text();self.assertNotIn(SECRET,saved);self.assertNotIn('password',saved)
        self.assertTrue(json.loads(saved)[UUID]['selectedMounted'])

    def test_wrong_password_returns_retry_prompt_and_preserves_lock(self):
        result=self.manager.set_mounted(UUID,True,password='wrong-fixture')
        self.assertTrue(result['requiresPassword']);self.assertFalse(result['drives'][0]['mounted'])
        self.assertTrue(result['drives'][0]['locked'])
        self.assertNotIn('selectedMounted',json.loads(self.path.read_text())[UUID])
        self.assertNotIn('wrong-fixture',json.dumps(result))

    def test_bad_password_payloads_rejected_before_native_commands(self):
        for password in ('',True,12,[], 'a\nb','a\rb','a\0b','å'*513):
            with self.subTest(password_type=type(password).__name__):
                with self.assertRaises(ValueError):self.manager.set_mounted(UUID,True,password=password)
        self.assertEqual(self.calls,[])
        with self.assertRaises(ValueError):self.manager.set_mounted(UUID,False,password=SECRET)

    def test_password_cannot_target_an_unlisted_drive(self):
        with self.assertRaises(ValueError):self.manager.set_mounted('22222222-2222-4222-8222-222222222222',True,password=SECRET)
        self.assertEqual(self.calls,[(('list',),None)])

    def test_native_receives_password_only_on_stdin(self):
        reply=SimpleNamespace(returncode=0,stdout=json.dumps(self.state))
        with patch('drives.subprocess.run',return_value=reply) as run:
            self.manager.native('unlock',UUID,password=SECRET)
            args,kwargs=run.call_args
            self.assertEqual(args[0],['unused','unlock',UUID])
            self.assertEqual(kwargs['input'],SECRET+'\n')
            self.assertNotIn(SECRET,repr(args))
            self.assertNotIn('shell',kwargs)

    def test_startup_never_retries_or_stores_a_password(self):
        self.manager.snapshot()
        self.manager.known[UUID]['selectedMounted']=True
        self.manager.restore()
        self.assertTrue(self.manager.known[UUID]['selectedMounted'])
        self.assertFalse(any(args[0]=='unlock' for args,_ in self.calls))

if __name__=='__main__':unittest.main()
