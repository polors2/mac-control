"""Native helper failure paths and history recovery with mocked SMC hardware."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'), 'macOS native helper tests')
class FanHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name) / 'learning'
        source = Path(cls.temp.name) / 'helper.m'
        source.write_text(r'''
#import "smc.h"
#include <unistd.h>
static int scenario, returnedToApple, sensorReads, fanReads;
static io_connect_t fakeOpen(void) { return 1; }
static kern_return_t fakeClose(io_connect_t c) { return 0; }
static id fakeTemperature(io_connect_t c, NSArray *keys, NSString *label) {
    sensorReads++;
    return scenario == 1 ? NSNull.null : @{@"celsius": @60};
}
static double fakeGet(io_connect_t c, const char *key) {
    fanReads++;
    if (!strcmp(key, "FNum")) return 2;
    if (!strcmp(key, "FS! ")) return 3;
    if (strstr(key, "Ac")) return scenario == 2 ? NAN : 3000;
    if (strstr(key, "Mn")) return 2000;
    if (strstr(key, "Mx")) return 6000;
    if (strstr(key, "Tg")) return 2000;
    if (strstr(key, "Md")) return 1;
    return NAN;
}
static BOOL fakeRead(io_connect_t c, const char *key, MCValue *v) {
    v->info.type = mcKey("ui8 "); v->info.size = 1; v->bytes[0] = 1; return YES;
}
static BOOL fakeSet(io_connect_t c, const char *key, double v) { return scenario != 3; }
static NSString *fakeMode(BOOL maximum) { if (!maximum) returnedToApple++; return nil; }
#define mcOpen fakeOpen
#define mcTemperature fakeTemperature
#define mcGet fakeGet
#define mcRead fakeRead
#define mcSet fakeSet
#define mcFanMode fakeMode
#define IOServiceClose fakeClose
#define MC_FAN_HISTORY_DIR @"HISTORY_DIRECTORY"
#import "fan_target.h"
int main(int argc, char **argv) {
    @autoreleasepool {
        scenario = atoi(argv[1]);
        if (scenario == 6) {
            MCFanModel continuous, restored; mcModelInit(&continuous);
            for (int i = 0; i < 300; i++)
                mcModelStep(&continuous, 2*i, 60+3*sin(i*.1), .4+.2*sin(i*.07), .5+.3*cos(i*.13), 70);
            NSDictionary *learned = mcLearningCheckpoint(&continuous);
            NSData *encoded = [NSJSONSerialization dataWithJSONObject:learned options:0 error:nil];
            BOOL loaded = mcRestoreLearning(&restored, [NSJSONSerialization JSONObjectWithData:encoded options:0 error:nil]);
            continuous.previous = false; continuous.demand = 1;
            for (int i = 300; i < 500; i++) {
                double temp = 62+2*sin(i*.13), load = .6+.2*sin(i*.11), fan = .5+.2*cos(i*.17);
                mcModelStep(&continuous, 2*i, temp, load, fan, 70);
                mcModelStep(&restored, 2*i, temp, load, fan, 70);
            }
            NSDictionary *result = @{@"loaded": @(loaded), @"learned": learned,
                @"continuous": mcLearningCheckpoint(&continuous), @"restored": mcLearningCheckpoint(&restored),
                @"forecastDifference": @(fabs(continuous.forecast-restored.forecast)),
                @"demandDifference": @(fabs(continuous.demand-restored.demand))};
            NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); return 0;
        }
        MCTargetController *controller = [MCTargetController new];
        NSDictionary *before = controller.status;
        if (scenario != 4 && scenario != 7) [controller start:70];
        if (scenario == 5) {
            // A path failure must leave the previous durable log intact.
            NSString *blocked = [MC_FAN_HISTORY_PATH stringByAppendingString:@".blocked"];
            [NSFileManager.defaultManager moveItemAtPath:MC_FAN_HISTORY_PATH toPath:blocked error:nil];
            [NSFileManager.defaultManager createDirectoryAtPath:MC_FAN_HISTORY_PATH withIntermediateDirectories:NO attributes:nil error:nil];
            [controller saveLearningAtTime:NSDate.date.timeIntervalSince1970+86401];
            NSDictionary *failed = controller.status;
            [NSFileManager.defaultManager removeItemAtPath:MC_FAN_HISTORY_PATH error:nil];
            [NSFileManager.defaultManager moveItemAtPath:blocked toPath:MC_FAN_HISTORY_PATH error:nil];
            [controller saveLearningAtTime:NSDate.date.timeIntervalSince1970+86401];
            NSDictionary *result = @{@"before": before, @"failed": failed, @"after": controller.status};
            NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); return 0;
        }
        [controller saveLearningAtTime:scenario == 7 ? strtod(argv[2], NULL) : NSDate.date.timeIntervalSince1970+(scenario == 4 ? 86401 : 0)];
        NSDictionary *result = @{@"before": before, @"after": controller.status,
                                  @"apple": @(returnedToApple), @"sensorReads": @(sensorReads), @"fanReads": @(fanReads)};
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
    }
}
'''.replace('HISTORY_DIRECTORY', str(cls.directory)))
        cls.binary = Path(cls.temp.name) / 'helper'
        subprocess.run(['clang', '-fobjc-arc', '-O2', '-I', str(ROOT/'native'),
                        '-framework', 'Foundation', '-framework', 'IOKit', str(source), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def run_helper(self, scenario=0, cleanup_time=None):
        command = [str(self.binary), str(scenario)]
        if cleanup_time is not None: command.append(str(cleanup_time))
        return json.loads(subprocess.check_output(command))

    def write_history(self, data):
        self.directory.mkdir(mode=0o700)
        (self.directory/'fan-learning.json').write_text(json.dumps(data))

    def assert_checkpoint_equal(self, actual, expected):
        self.assertEqual(actual['samples'], expected['samples'])
        self.assertAlmostEqual(actual['error'], expected['error'], places=10)
        for key in ['theta', 'rhs', 'gram']:
            self.assertEqual(len(actual[key]), len(expected[key]))
            for a, b in zip(actual[key], expected[key]):
                self.assertAlmostEqual(a, b, places=10)  # JSON double round trips.

    def test_sensor_fan_and_write_failures_return_to_apple(self):
        for scenario in [1, 2, 3]:
            result = self.run_helper(scenario)
            self.assertEqual(result['after']['controllerMode'], 'manual-or-auto')
            self.assertIn('Returned', result['after']['controllerError'])
            self.assertGreater(result['apple'], 0)

    def test_private_log_written_and_bounded_history_replayed(self):
        self.write_history({'version': 1, 'samples': [[time.time()-600+2*i, 60+i*.01, .4, .5] for i in range(300)]})
        result = self.run_helper()
        self.assertEqual(result['before']['learningSamples'], 299)
        self.assertEqual(result['after']['controllerMode'], 'target')
        path = self.directory/'fan-learning.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(len(json.loads(path.read_text())['samples']), 300)

    def test_restart_retains_learning_but_discards_stale_temperature_and_mode(self):
        self.write_history({'version': 1, 'samples': [[1000+2*i, 60+i*.01, .4, .5] for i in range(100)]})
        result = self.run_helper()
        self.assertEqual(result['before']['controllerMode'], 'manual-or-auto')
        self.assertEqual(result['before']['coolingDemand'], 1)
        self.assertNotIn('predictedTemperature', result['before'])
        self.assertEqual(result['before']['learningSamples'], result['after']['learningSamples'])

    def test_malformed_rows_are_skipped(self):
        self.write_history({'version': 1, 'samples': [None, {}, [1, 2], ['bad', 60, .5, .5],
                           [100, 60, .5, .5], [102, 61, 'NaN', .5], [104, 60, .5, .5]]})
        result = self.run_helper()
        self.assertEqual(result['before']['learningSamples'], 1)
        self.assertEqual(result['after']['controllerMode'], 'target')

    def test_corrupt_json_does_not_prevent_target_control(self):
        self.directory.mkdir(mode=0o700)
        (self.directory/'fan-learning.json').write_text('{"version":1,"samples":[[100,60,NaN,0.5]]}')
        result = self.run_helper()
        self.assertEqual(result['before']['learningSamples'], 0)
        self.assertEqual(result['after']['controllerMode'], 'target')

    def test_expired_legacy_logs_are_learned_before_deletion_and_survive_restart(self):
        rows = [[time.time()-90000+2*i, 60+i*.01, .4, .5] for i in range(100)]
        self.write_history({'version': 1, 'samples': rows})
        first = self.run_helper(4)  # Retention maintenance with Target disabled.
        saved = json.loads((self.directory/'fan-learning.json').read_text())
        self.assertEqual(saved['version'], 2)
        self.assertEqual(saved['samples'], [])
        self.assertEqual(saved['model']['samples'], 99)
        self.assertNotEqual(saved['model']['theta'], [.15, -.4, 1., .8])
        self.assertGreater(saved['model']['gram'][0], 0)
        second = self.run_helper(4)
        self.assertEqual(first['before']['learningSamples'], 99)
        self.assertEqual(second['before']['learningSamples'], 99)
        self.assertEqual(first['before']['coolingEffect'], second['before']['coolingEffect'])
        self.assert_checkpoint_equal(saved['model'], json.loads((self.directory/'fan-learning.json').read_text())['model'])

    def test_checkpointed_rows_are_not_learned_twice_on_restart(self):
        self.write_history({'version': 1, 'samples': [[time.time()-600+2*i, 60+i*.01, .4, .5] for i in range(100)]})
        self.run_helper()
        path = self.directory/'fan-learning.json'
        saved = json.loads(path.read_text())
        self.assertGreater(len(saved['samples']), 0)
        second = self.run_helper()
        third = self.run_helper()
        self.assertEqual(saved['model']['samples'], second['before']['learningSamples'])
        self.assertEqual(second['before']['learningSamples'], third['before']['learningSamples'])
        self.assert_checkpoint_equal(saved['model'], json.loads(path.read_text())['model'])

    def test_retention_preserves_checkpoint_even_when_no_new_samples_arrive(self):
        self.write_history({'version': 1, 'samples': [[time.time()-600+2*i, 60+i*.01, .4, .5] for i in range(100)]})
        self.run_helper()
        path = self.directory/'fan-learning.json'
        saved = json.loads(path.read_text())
        self.assertGreater(len(saved['samples']), 0)
        result = self.run_helper(4)
        expired = json.loads(path.read_text())
        self.assertEqual(expired['samples'], [])
        self.assert_checkpoint_equal(expired['model'], saved['model'])
        self.assertEqual(result['after']['controllerMode'], 'manual-or-auto')
        self.assertEqual(result['sensorReads'], 0)
        self.assertEqual(result['fanReads'], 0)

    def test_failed_cleanup_keeps_learning_and_retries_successfully(self):
        self.write_history({'version': 1, 'samples': [[time.time()-600+2*i, 60+i*.01, .4, .5] for i in range(100)]})
        self.run_helper()
        result = self.run_helper(5)
        self.assertIn('learningWarning', result['failed'])
        self.assertNotIn('learningWarning', result['after'])
        self.assertEqual(result['before']['learningSamples'], result['after']['learningSamples'])
        saved = json.loads((self.directory/'fan-learning.json').read_text())
        self.assertEqual(saved['samples'], [])
        self.assertEqual(saved['model']['samples'], result['before']['learningSamples'])

    def test_corrupt_checkpoint_falls_back_to_learning_from_raw_log(self):
        self.write_history({'version': 1, 'samples': [[time.time()-600+2*i, 60+i*.01, .4, .5] for i in range(100)]})
        self.run_helper()
        path = self.directory/'fan-learning.json'
        saved = json.loads(path.read_text())
        for key, value in [('theta', []), ('error', 'invalid'), ('gram', [-9999]*16), ('samples', -1)]:
            damaged = json.loads(json.dumps(saved))
            damaged['model'][key] = value
            path.write_text(json.dumps(damaged))
            result = self.run_helper(4)
            self.assertGreater(result['before']['learningSamples'], 0)
            self.assertEqual(result['before']['controllerMode'], 'manual-or-auto')
            repaired = json.loads(path.read_text())['model']
            self.assertGreater(repaired['samples'], 0)
            self.assertTrue(.15 <= repaired['theta'][3] <= 4)

    def test_invalid_raw_list_is_removed_without_losing_valid_checkpoint(self):
        self.write_history({'version': 1, 'samples': [[time.time()-600+2*i, 60+i*.01, .4, .5] for i in range(100)]})
        self.run_helper()
        path = self.directory/'fan-learning.json'
        saved = json.loads(path.read_text())
        for rows in ['invalid', [[1000+2*i, 60, .4, .5] for i in range(301)]]:
            damaged = json.loads(json.dumps(saved)); damaged['samples'] = rows
            path.write_text(json.dumps(damaged))
            self.run_helper(4)
            repaired = json.loads(path.read_text())
            self.assertEqual(repaired['samples'], [])
            self.assert_checkpoint_equal(repaired['model'], saved['model'])

    def test_learning_continues_after_restore_with_same_forecast_and_fan_demand(self):
        result = self.run_helper(6)
        self.assertTrue(result['loaded'])
        self.assert_checkpoint_equal(result['continuous'], result['restored'])
        self.assertGreater(result['restored']['samples'], result['learned']['samples'])
        self.assertNotEqual(result['restored']['theta'], result['learned']['theta'])
        self.assertAlmostEqual(result['forecastDifference'], 0, places=10)
        self.assertAlmostEqual(result['demandDifference'], 0, places=10)

    def test_retention_expires_only_rows_older_than_24_hours(self):
        now = time.time(); cleanup = now+1000
        timestamps = [cleanup-86400-.01, cleanup-86400, cleanup-86400+.01, now-30]
        self.write_history({'version': 1, 'samples': [[t, 60, .4, .5] for t in timestamps]})
        self.run_helper(7, cleanup_time=cleanup)
        saved = json.loads((self.directory/'fan-learning.json').read_text())
        self.assertEqual([row[0] for row in saved['samples']], timestamps[1:])

    def test_unavailable_log_keeps_session_control_running_and_reports_warning(self):
        self.directory.mkdir(mode=0o755)
        result = self.run_helper()
        self.assertIn('learningWarning', result['after'])
        self.assertEqual(result['after']['controllerMode'], 'target')
        self.assertFalse((self.directory/'fan-learning.json').exists())


if __name__ == '__main__': unittest.main()
