"""Run frontend interaction regressions in macOS JavaScriptCore."""
import ctypes as C
import json
from pathlib import Path
import sys
import unittest


@unittest.skipUnless(sys.platform == 'darwin', 'JavaScriptCore is supplied by macOS')
class WebInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = C.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore')
        for name, (args, result) in {
            'JSGlobalContextCreate': ([C.c_void_p], C.c_void_p),
            'JSGlobalContextRelease': ([C.c_void_p], None),
            'JSStringCreateWithUTF8CString': ([C.c_char_p], C.c_void_p),
            'JSStringRelease': ([C.c_void_p], None),
            'JSEvaluateScript': ([C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.POINTER(C.c_void_p)], C.c_void_p),
            'JSValueToStringCopy': ([C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)], C.c_void_p),
            'JSStringGetMaximumUTF8CStringSize': ([C.c_void_p], C.c_size_t),
            'JSStringGetUTF8CString': ([C.c_void_p, C.c_void_p, C.c_size_t], C.c_size_t),
        }.items():
            getattr(cls.js, name).argtypes = args
            getattr(cls.js, name).restype = result
        cls.web = Path(__file__).parent / 'web'

    def evaluate(self, script):
        js = self.js
        context = js.JSGlobalContextCreate(None)
        source = js.JSStringCreateWithUTF8CString(script.encode())
        exception = C.c_void_p()
        string = None
        try:
            value = js.JSEvaluateScript(context, source, None, None, 1, C.byref(exception))
            if exception.value:
                value = exception.value
            string = js.JSValueToStringCopy(context, value, None)
            length = js.JSStringGetMaximumUTF8CStringSize(string)
            buffer = C.create_string_buffer(length)
            js.JSStringGetUTF8CString(string, buffer, length)
            self.assertFalse(exception.value, buffer.value.decode())
            return json.loads(buffer.value.decode())
        finally:
            if string:
                js.JSStringRelease(string)
            js.JSStringRelease(source)
            js.JSGlobalContextRelease(context)

    def nearest(self, points, time, distance=3):
        source = (self.web / 'chart-inspector.js').read_text().split('const chartInspectors')[0]
        return self.evaluate(source + f'\nJSON.stringify(nearestChartPoint({json.dumps(points)},{time},{distance}));')

    def test_chart_selects_real_sample_without_interpolating_values(self):
        self.assertEqual(self.nearest([{'time': 100, 'value': 42}, {'time': 102, 'value': 80}], 101.5),
                         {'time': 102, 'value': 80})

    def test_chart_preserves_missing_samples_and_large_gaps(self):
        self.assertEqual(self.nearest([{'time': 100, 'value': 42}, {'time': 102, 'value': None}], 102),
                         {'time': 102, 'value': None})
        self.assertIsNone(self.nearest([{'time': 100, 'value': 42}, {'time': 180, 'value': 80}], 140))
        self.assertIsNone(self.nearest([], 100))

    def test_chart_keeps_zero_as_a_real_value(self):
        self.assertEqual(self.nearest([{'time': 100, 'value': 0}], 100)['value'], 0)

    def test_mobile_tab_switch_preserves_visual_position_and_keyboard_focus(self):
        source = (self.web / 'app.js').read_text().split('function selectPanel(')[1].split('function sizeMobilePanels')[0]
        script = '''
          const main={scrollTop:500}, tabs={getBoundingClientRect:()=>({top:document.body.dataset.panel==='inputs' ? 140:120})};
          let focusOptions=null;
          const button={dataset:{panel:'inputs'},setAttribute(){},focus(options){focusOptions=options;}};
          const document={body:{dataset:{panel:'controls'}},querySelectorAll:()=>[button]};
          const $=selector=>selector==='main' ? main:selector==='.panel-tabs' ? tabs:{setAttribute(){}};
          const matchMedia=()=>({matches:true});
        ''' + 'function selectPanel(' + source + '''
          selectPanel('inputs',true);
          JSON.stringify({scroll:main.scrollTop,panel:document.body.dataset.panel,focusOptions});
        '''
        self.assertEqual(self.evaluate(script), {'scroll': 520, 'panel': 'inputs', 'focusOptions': {'preventScroll': True}})

    def test_every_frontend_script_parses(self):
        scripts = {path.name: path.read_text() for path in self.web.glob('*.js')}
        self.assertTrue(self.evaluate('const scripts=' + json.dumps(scripts) + '; Object.values(scripts).forEach(source=>new Function(source)); JSON.stringify(true);'))

    def drive_action(self,drive,password=None,mount=None):
        source=(self.web/'drives.js').read_text().split('async function changeDrive(')[1].split("$('#drive-unlock-form')")[0]
        script='''
          const pendingDrives=new Map(), driveData=[];
          let driveGeneration=0,driveTimer,prompted=false,request=null;
          const promptUnlock=()=>{prompted=true;};
          const renderDrives=()=>{}, clearTimeout=()=>{};
          const api=(path,body)=>{request=body;return new Promise(()=>{});};
        '''+'async function changeDrive('+source+f'''
          changeDrive({json.dumps(drive)},{json.dumps(password)},{json.dumps(mount)});
          JSON.stringify({{prompted,request,generation:driveGeneration}});
        '''
        return self.evaluate(script)

    def test_unlock_button_never_unmounts_a_partially_locked_drive(self):
        self.assertEqual(self.drive_action({'id':'fixture','mounted':True,'locked':True}),
                         {'prompted':True,'request':None,'generation':0})

    def test_password_retry_requests_mount_and_invalidates_prior_poll(self):
        result=self.drive_action({'id':'fixture','mounted':True,'locked':False},'fixture-only-password',True)
        self.assertEqual(result['request']['mounted'],True)
        self.assertEqual(result['generation'],1)


if __name__ == '__main__':
    unittest.main()
