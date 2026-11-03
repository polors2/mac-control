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

    def claude_pill(self, data, signed_in=True, now=1_800_000_000, provider="claude"):
        five, seven = ("claude-five-hour", "claude-seven-day") if provider == "claude" else ("codex-primary", "codex-secondary")
        source = (self.web / 'host-status.js').read_text().split('const claudeResetClock')[1].split('function scheduleHostStatus')[0]
        script = f'''
          const authenticated={json.dumps(signed_in)};
          Date.now=()=>{now}*1000;
          const element=()=>{{const classes=new Set();return {{hidden:false,textContent:'',title:'',style:{{}},classes,
            classList:{{toggle(name,on){{on ? classes.add(name):classes.delete(name);}}}}}};}};
          const nodes={{'#{provider}-usage':element(),'#{provider}-note':element()}};
          for(const id of ['#{five}','#{seven}','#claude-model-week']) {{
            const item=element(), strong=element(), meter=element(), label=element();
            item.querySelector=selector=>selector==='strong' ? strong:selector==='.claude-window-label' ? label:meter;
            item.strong=strong;item.meter=meter;item.label=label;nodes[id]=item;
          }}
          const $=selector=>nodes[selector];
        ''' + 'const claudeResetClock' + source + f'''
          render{provider.title()}Usage({json.dumps(data)});
          const view=id=>({{hidden:nodes[id].hidden,text:nodes[id].strong.textContent,width:nodes[id].meter.style.width,classes:[...nodes[id].classes].sort()}});
          JSON.stringify({{note:nodes['#{provider}-note'].textContent,noteHidden:nodes['#{provider}-note'].hidden,
            stale:nodes['#{provider}-usage'].classes.has('is-stale'),title:nodes['#{provider}-usage'].title,
            five:view('#{five}'),seven:view('#{seven}'),fiveLabel:nodes['#{five}'].label.textContent,
            model:{{...view('#claude-model-week'),label:nodes['#claude-model-week'].label.textContent}}}});
        '''
        return self.evaluate(script)

    def test_claude_usage_pill_shows_fable_weekly_only_when_reported(self):
        now = 1_800_000_000
        base = {'state': 'available', 'updatedAt': now - 60, 'fiveHour': {'usedPercent': 34, 'resetsAt': now + 3600},
                'sevenDay': {'usedPercent': 9, 'resetsAt': now + 86400}}
        result = self.claude_pill({'claude': {**base, 'modelWeekly': [
            {'name': 'Sonnet', 'usedPercent': 50, 'resetsAt': now + 86400},
            {'name': 'Fable', 'usedPercent': 82.4, 'resetsAt': now + 86400}]}})
        self.assertEqual(result['model'], {'hidden': False, 'text': '82%', 'width': '82%', 'classes': ['is-high'], 'label': 'Fable'})
        self.assertIn('Fable weekly: 82% used', result['title'])
        self.assertIn('Sonnet weekly: 50% used', result['title'])
        for models in [[], None, [{'name': 'Fable', 'usedPercent': None}], [{'usedPercent': 5}]]:
            with self.subTest(models=models):
                self.assertTrue(self.claude_pill({'claude': {**base, 'modelWeekly': models}})['model']['hidden'])
        self.assertTrue(self.claude_pill({'claude': {'state': 'unavailable', 'modelWeekly': [
            {'name': 'Fable', 'usedPercent': 5, 'resetsAt': now + 60}]}})['model']['hidden'])

    def test_claude_usage_pill_rounds_clamps_and_flags_high_usage(self):
        now = 1_800_000_000
        result = self.claude_pill({'claude': {'state': 'available', 'updatedAt': now - 60,
                                              'fiveHour': {'usedPercent': 79.6, 'resetsAt': now + 3600},
                                              'sevenDay': {'usedPercent': 100, 'resetsAt': now + 86400}}})
        self.assertEqual(result['five'], {'hidden': False, 'text': '80%', 'width': '80%', 'classes': ['is-high']})
        self.assertEqual(result['seven'], {'hidden': False, 'text': '100%', 'width': '100%', 'classes': ['is-full']})
        self.assertEqual((result['note'], result['noteHidden'], result['stale']), ('', True, False))
        self.assertIn('Updated from Claude Code 1 min ago', result['title'])

    def test_claude_usage_pill_states_never_invent_readings(self):
        now = 1_800_000_000
        stale = self.claude_pill({'claude': {'state': 'available', 'updatedAt': now - 7200, 'fiveHour': None,
                                             'sevenDay': {'usedPercent': 12, 'resetsAt': now + 86400}}})
        self.assertEqual(stale['five'], {'hidden': False, 'text': '—', 'width': '0%', 'classes': []})
        self.assertTrue(stale['stale'])
        for data, signed_in, note in [({'claude': {'state': 'not-configured'}}, True, 'Set up'),
                                      ({'claude': {'state': 'unavailable'}}, True, 'Unavailable'),
                                      ({}, True, 'Unavailable'), (None, True, 'Checking…'),
                                      ({'claude': {'state': 'available', 'fiveHour': {'usedPercent': 5}}}, False, 'Sign in')]:
            with self.subTest(note=note):
                result = self.claude_pill(data, signed_in)
                self.assertEqual((result['note'], result['noteHidden']), (note, False))
                self.assertTrue(result['five']['hidden'] and result['seven']['hidden'])
                self.assertEqual(result['five']['text'], '—')

    def test_codex_usage_shows_actual_windows_and_expiry(self):
        now = 1_800_000_000
        usage = {'state': 'available', 'updatedAt': now - 60,
                 'primary': {'usedPercent': 80, 'resetsAt': now + 3600, 'windowMinutes': 300},
                 'secondary': {'usedPercent': 100, 'resetsAt': now + 86400, 'windowMinutes': 10080}}
        result = self.claude_pill({'codex': usage}, provider='codex')
        self.assertEqual(result['five'], {'hidden': False, 'text': '80%', 'width': '80%', 'classes': ['is-high']})
        self.assertEqual(result['seven']['text'], '100%')
        self.assertIn('is-full', result['seven']['classes'])
        self.assertIn('7d: 100% used', result['title'])
        self.assertIn('Manila', result['title'])
        self.assertEqual(result['fiveLabel'], '5h')
        usage['primary']['windowMinutes'] = 15
        usage['secondary']['resetsAt'] = now - 1
        usage['updatedAt'] = now - 7200
        result = self.claude_pill({'codex': usage}, provider='codex')
        self.assertEqual(result['fiveLabel'], '15m')
        self.assertEqual(result['seven']['text'], '—')
        self.assertTrue(result['stale'])

    def test_codex_usage_states_clear_readings_when_signed_out(self):
        for data, signed_in, note in [(None, True, 'Checking…'), ({'codex': {'state': 'checking'}}, True, 'Checking…'),
                                     ({'codex': {'state': 'not-configured'}}, True, 'Set up'),
                                     ({'codex': {'state': 'unavailable'}}, True, 'Unavailable'),
                                     ({'codex': {'state': 'available', 'primary': {'usedPercent': 8}}}, False, 'Sign in')]:
            with self.subTest(note=note):
                result = self.claude_pill(data, signed_in, provider='codex')
                self.assertEqual(result['note'], note)
                self.assertTrue(result['five']['hidden'] and result['seven']['hidden'])
                self.assertEqual(result['five']['text'], '—')

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
