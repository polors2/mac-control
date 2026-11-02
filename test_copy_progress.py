"""Exercise the actual frontend selector with macOS's built-in JavaScriptCore."""
import ctypes as C
import json
from pathlib import Path
import sys
import unittest

@unittest.skipUnless(sys.platform=='darwin','JavaScriptCore is supplied by macOS')
class CopyProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js=C.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore')
        signatures={
            'JSGlobalContextCreate':([C.c_void_p],C.c_void_p),
            'JSGlobalContextRelease':([C.c_void_p],None),
            'JSStringCreateWithUTF8CString':([C.c_char_p],C.c_void_p),
            'JSStringRelease':([C.c_void_p],None),
            'JSEvaluateScript':([C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_int,C.POINTER(C.c_void_p)],C.c_void_p),
            'JSValueToStringCopy':([C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)],C.c_void_p),
            'JSStringGetMaximumUTF8CStringSize':([C.c_void_p],C.c_size_t),
            'JSStringGetUTF8CString':([C.c_void_p,C.c_void_p,C.c_size_t],C.c_size_t),
        }
        for name,(args,result) in signatures.items():
            getattr(cls.js,name).argtypes=args;getattr(cls.js,name).restype=result
        cls.source=(Path(__file__).parent/'web/notifier-activity.js').read_text().split('// DOM rendering.')[0]

    def select(self,data):
        js=self.js;context=js.JSGlobalContextCreate(None)
        script=js.JSStringCreateWithUTF8CString((self.source+'\nJSON.stringify(copyProgressRows('+json.dumps(data)+'));').encode())
        exception=C.c_void_p();string=None
        try:
            value=js.JSEvaluateScript(context,script,None,None,1,C.byref(exception))
            self.assertFalse(exception.value,'The frontend selector threw a JavaScript exception')
            string=js.JSValueToStringCopy(context,value,C.byref(exception))
            length=js.JSStringGetMaximumUTF8CStringSize(string);buffer=C.create_string_buffer(length)
            js.JSStringGetUTF8CString(string,buffer,length)
            return json.loads(buffer.value.decode())
        finally:
            if string:js.JSStringRelease(string)
            js.JSStringRelease(script);js.JSGlobalContextRelease(context)

    def finder(self,identifier='real'):
        return {'id':identifier,'text':'Copying 12 items to Example Drive · 5 GB of 10 GB - About 2 minutes','percent':50,'status':'visible_in_finder'}

    def transfer(self,**changes):
        return {'id':'managed','display_name':'Example transfer','provider':'managed','status':'running','bytes_done':500,'bytes_total':1000,**changes}

    def test_screenshot_regression_keeps_detailed_copy_and_drops_seven_generic_rows(self):
        noise=[{'id':str(i),'display_name':'Finder file operation','provider':'finder','status':'running' if i<2 else 'no_longer_visible','percent':10 if i<2 else None} for i in range(7)]
        rows=self.select({'finder_progress':{'items':[self.finder()]},'transfers':noise})
        self.assertEqual([row['id'] for row in rows],['real'])

    def test_percentage_without_details_is_not_a_copy_row(self):
        self.assertEqual(self.select({'finder_progress':{'items':[{'id':'empty','text':'Copying items','percent':50}]},'transfers':[self.transfer(bytes_done=None,bytes_total=None)]}),[])

    def test_sidebar_and_calculating_placeholders_are_hidden(self):
        items=[{'id':'nav','text':'Favourites · AirDrop · All Tags','percent':7},{'id':'wait','text':'Preparing to copy · Calculating…','percent':0}]
        self.assertEqual(self.select({'finder_progress':{'items':items}}),[])

    def test_stale_and_terminal_entries_are_not_rendered(self):
        for status in ('no_longer_visible','completed','failed','cancelled','unknown_after_restart'):
            self.assertEqual(self.select({'transfers':[self.transfer(status=status)]}),[])

    def test_real_managed_transfer_with_byte_counts_is_kept(self):
        rows=self.select({'transfers':[self.transfer()]})
        self.assertEqual([row['id'] for row in rows],['managed'])
        self.assertIn('500 B',rows[0]['detail'])

    def test_detailed_finder_copy_suppresses_its_registry_duplicate(self):
        duplicate=self.transfer(provider='finder',display_name='Copying 12 items')
        rows=self.select({'finder_progress':{'items':[self.finder()]},'transfers':[duplicate]})
        self.assertEqual([row['id'] for row in rows],['real'])

    def test_two_distinct_detailed_copies_are_preserved(self):
        rows=self.select({'finder_progress':{'items':[self.finder('one'),self.finder('two')]}})
        self.assertEqual([row['id'] for row in rows],['one','two'])

if __name__=='__main__':unittest.main()
