#!/usr/bin/python3
# SPDX-License-Identifier: BSD-3 Clause
__copyright__ = 'Copyright (C) 2020, Nokia'

import argparse
import io
import json
import os
import logging as log
import pathlib
import subprocess as sp
import sys
import time

import matplotlib.pyplot as plt
import numpy as np

log.basicConfig(level=log.INFO)

plt.style.use('ggplot')


def get_all_subclasses(cls):
    klasses = {}
    pending = cls.__subclasses__()
    while pending:
        k = pending.pop()
        if k.__name__ in klasses:
            continue
        pending.extend(k.__subclasses__())
        klasses[k.__name__] = k
    return klasses


class CCA(object):
    ALL = {}

    @classmethod
    def discover_subclasses(cls):
        cls.ALL = get_all_subclasses(cls)

    @classmethod
    def get(cls, name):
        try:
            return cls.ALL[name]
        except KeyError as e:
            log.exception('Unknown congestion control %s', name)
            sys.exit()

    @classmethod
    def as_json(cls):
        return cls.__name__


class Cubic(CCA):
    NAME = 'cubic'
    COLOR = 'orange'

    @classmethod
    def configure(cls):
        return cls

    @classmethod
    def pretty_name(cls):
        return cls.NAME


class Prague(Cubic):
    NAME = 'prague'
    COLOR = 'blue'
    PARAMS = {
        'rtt_scaling': '0',
        'rtt_target': '15000',
       # 'ecn_fallback': '0'
    }

    @classmethod
    def prague_params(cls):
        for k, w in cls.PARAMS.items():
            with open('/sys/module/tcp_prague/parameters/prague_%s' % k,
                      'w') as f:
                f.write(w)

    @classmethod
    def configure(cls):
        cls.prague_params()
        return cls

    @classmethod
    def pretty_name(cls):
        return '%s (%s)' % (cls.NAME,
                            ','.join(('%s=%s' % (k, v)
                                      for k, v in cls.PARAMS.items())))


class PragueClassic(Prague):
    PARAMS = Prague.PARAMS.copy()
    PARAMS['ecn_fallback'] = '1'


class PragueRTTIndep(Prague):
    PARAMS = Prague.PARAMS.copy()
    PARAMS['rtt_scaling'] = '1'
    COLOR = '#1c9099'


class PragueRTTIndepAdditive(Prague):
    PARAMS = Prague.PARAMS.copy()
    PARAMS['rtt_scaling'] = '3'
    COLOR = 'purple'


def avg_series(x, t, period):
    avg = np.empty(len(x))
    start = 0
    s = 0
    # Compute the rolling average over @period
    for i, (b, ts) in enumerate(zip(x, t)):
        while ts - t[start] > period:
            s -= x[start]
            start += 1
        s += b
        avg[i] = s / (i - start + 1)
    return avg


class Test(object):
    CWD = pathlib.Path(__file__).parent.absolute()
    SCRIPT = CWD / 'test_bottleneck.sh'
    DATA_DIR = CWD
    DELAYS = [0.5, 1, 5, 10, 15, 20, 30, 40, 50]  # ms
    INTERVAL = 100  # sec
    BW_SCALE = 1_000_000  # Mb
    MAX_BW = 100
    AQM = 'dualpi2'
    _CFG = "test_cfg.json"

    def __init__(self, cc1=Prague, cc2=Cubic):
        self.cc1 = cc1
        self.cc2 = cc2
        self.env = self.build_env()

    @classmethod
    def cfg_file(cls):
        return cls.DATA_DIR / cls._CFG

    @classmethod
    def save_config(cls, testplan):
        with open(cls.cfg_file(), 'w') as f:
            json.dump(dict(data_dir=str(cls.DATA_DIR),
                           delays=cls.DELAYS,
                           interval=cls.INTERVAL,
                           max_bw=cls.MAX_BW,
                           aqm=cls.AQM,
                           testplan=[t.as_json() for t in testplan]),
                      f)

    def as_json(self):
        return dict(test_type=self.__class__.__name__,
                    env=self.env, cc1=self.cc1.as_json(),
                    cc2=self.cc2.as_json())

    @classmethod
    def args_from_json(cls, j):
        return dict(cc1=CCA.get(j['cc1']), cc2=CCA.get(j['cc2']))

    @classmethod
    def from_json(cls, j):
        obj = cls(**cls.args_from_json(j))
        obj.env = j['env']
        return obj

    @classmethod
    def load_config(cls):
        test_types = get_all_subclasses(cls)
        test_types[cls.__name__] = cls
        CCA.discover_subclasses()

        with open(cls.cfg_file(), 'r') as f:
            data = json.load(f)
        try:
            cls.DELAYS = [float(d) for d in data['delays']]
            cls.INTERVAL = int(data['interval'])
            cls.MAX_BW = int(data['max_bw'])
            cls.AQM = data['aqm']
            return [test_types[t['test_type']].from_json(t)
                    for t in data['testplan']]
        except KeyError as e:
            log.exception('Corrupted test config file')
            sys.exit()

    def configure(self):
        self.cc2.configure()
        self.cc1.configure()

    def build_env(self):
        return {
            'AQM': self.AQM,
            'RATE': '%dMbit' % self.MAX_BW,
            'DELAY': '%fms' % self.DELAYS[0],
            'C1_CCA': self.cc1.NAME,
            'C2_CCA': self.cc2.NAME,
            'TIME': '%d' % self.duration,
            'LOG_PATTERN': self.log_pattern,
            'DATA_DIR': str(self.DATA_DIR)
        }

    def update_delay(self, delay):
        log.info('Switching to %fms as base delay', delay)
        self.env.update({'DELAY': '%fms' % delay})

    def run_test(self):
        log.info('Running %s vs %s', self.cc1.pretty_name(),
                 self.cc2.pretty_name())
        self.configure()

        self.env.update(os.environ)

        try:
            sp.check_call([self.SCRIPT, '-cs'], env=self.env)
        except sp.CalledProcessError as e:
            log.exception('Could not start test network')
            sys.exit()

        process = sp.Popen([self.SCRIPT, '-t'], env=self.env)
        # This one instance will need to setup the AQM and start the processes,
        # leave some headroom
        time.sleep(self.INTERVAL + 0.2)

        for delay in self.DELAYS[1:]:
            self.update_delay(delay)
            try:
                sp.check_call([self.SCRIPT, '-u'], env=self.env)
            except sp.CalledProcessError as e:
                log.exception('Failed to update the network')
                sys.exit()
            time.sleep(self.INTERVAL)

        # Wait for iperf to stop/flush
        process.wait()

    @property
    def duration(self):
        return self.INTERVAL * len(self.DELAYS)

    @property
    def log_pattern(self):
        return '%s_%s'% (self.cc1.__name__, self.cc2.__name__)

    def process_data(self, client):
        results = self.DATA_DIR / (
            'iperf_%s_%s.json' % (client, self.env['LOG_PATTERN']))
        try:
            with open(results, 'r') as input_data:
                data = json.load(input_data)
        except IOError as e:
            log.exception("Could not load the results for client '%s'", client)
            sys.exit()
        throughput = np.empty(len(data['intervals']))
        t = np.empty(len(data['intervals']))
        for i, d in enumerate(data['intervals']):
            throughput[i] = d['streams'][0]['bits_per_second'] / self.BW_SCALE
            t[i] = d['streams'][0]['end']
        return throughput, t

    @property
    def rtt_label(self):
        return 'Base RTT\n[ms]'

    @property
    def cc1_name(self):
        return self.cc1.pretty_name()

    @property
    def cc2_name(self):
        return self.cc2.pretty_name()

    def plot(self):
        log.info('Plotting %s vs %s', self.cc1.pretty_name(),
                 self.cc2.pretty_name())

        fig, ax = plt.subplots(figsize=(9, 4))
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('Throughput [Mbps]')
        ax.set_ylim(-1, self.MAX_BW)
        ax.set_xlim(-1, self.duration)
        ax.set_yticks([0, self.MAX_BW / 4, self.MAX_BW / 2,
                       self.MAX_BW * 3 / 4, self.MAX_BW])
        ax.set_xticks([i * self.INTERVAL for i in range(len(self.DELAYS))])

        for cc, data, name in ((self.cc1, 'c1', self.cc1_name),
                               (self.cc2, 'c2', self.cc2_name)):
            log.info('.. for client=%s', data)
            color = cc.COLOR
            bw, t= self.process_data(data)
            avg = avg_series(bw, t, 3.0)
            # ax.fill_between(t, avg, bw, color=color, alpha=.2)
            ax.plot(t, avg, label=name,
                     color=color, alpha=.8, linewidth=1)

        # Base RTT label top bar
        start = 0
        top = self.MAX_BW + self.MAX_BW / 20
        ax.text(-1, top, self.rtt_label, ha="right", va="bottom", color='gray')
        for rtt in self.DELAYS:
            end = start + self.INTERVAL
            ax.annotate("", xy=(start, top), xycoords='data',
                        xytext=(end, top), textcoords='data',
                        annotation_clip=False,
                        arrowprops=dict(arrowstyle="|-|", color='gray',
                                        linewidth=1))
            ax.text(start + self.INTERVAL / 2, top, '%.9g' % rtt,
                    ha="center", va="bottom", color='gray')
            start = end

        ax.legend()
        fig.savefig(self.fig_name('pdf'))
        fig.savefig(self.fig_name('png'), transparent=False, dpi=300)

    def fig_name(self, ext='pdf'):
        return str(self.DATA_DIR /
                   ('%s.%s' % (self.log_pattern, ext)))

    @classmethod
    def gen_report(cls, testplan):
        with open(cls.DATA_DIR / 'README.md', 'w') as f:
            f.write("""
# Description

Tests run on a `{MAX_BW}Mbps` bottleneck. The applied delay changed every {interval}s.

See the [test config file]({cfg}).

""".format(MAX_BW=cls.MAX_BW, cfg=cls._CFG, interval=cls.INTERVAL))

            headings = ["Test-%s: %s vs %s" % (i + 1, t.cc1.__name__,
                                               t.cc2.__name__)
                        for i, t in enumerate(testplan)]
            for h in headings:
                f.write(" * [{h}](#{link})\n".format(h=h,
                                                     link=h
                                                     .replace(' ', '-')
                                                     .replace(':','')
                                                     .lower()))

            for t, h in zip(testplan, headings):
                f.write("""
# {h}

CCA for flow (1): {cc1}

CCA for flow (2): {cc2}

Varying {rtt_label} in `{delays}`

![Result graph]({graph})

[Go back to index](#description)
""".format(h=h, cc1=t.cc1.pretty_name(), cc2=t.cc2.pretty_name(),
           rtt_label=t.rtt_label, delays=cls.DELAYS, graph=t.fig_name('png')))


class AsymTest(Test):

    def __init__(self, cc2_delay, *a, **kw):
        self.cc2_delay = cc2_delay
        super(AsymTest, self).__init__(*a, **kw)

    @property
    def cc1_name(self):
        return '(1) %s, variable base RTT' % self.cc1.pretty_name()

    @property
    def cc2_name(self):
        return '(2) prague (rtt_scaling=0), 15ms base RTT'

    @property
    def rtt_label(self):
        return 'Base RTT of\nflow (1) [ms]'

    @property
    def log_pattern(self):
        return '%s_%s-%fms'% (self.cc1.__name__, self.cc2.__name__,
                              self.cc2_delay)

    def build_env(self):
        env = super(AsymTest, self).build_env()
        try:
            del env['DELAY']
        except KeyError:
            pass
        env.update({
            'CC1_DELAY': '%fms' % self.DELAYS[0],
            'CC2_DELAY': '%fms' % self.cc2_delay
        })
        return env

    def update_delay(self, delay):
        log.info('Switching base delays to: c1->%fms, c2->%fms', delay,
                 self.cc2_delay)
        self.env['CC1_DELAY'] = '%fms' % delay

    def as_json(self):
        j = super(AsymTest, self).as_json()
        j['cc2_delay'] = self.cc2_delay
        return j

    @classmethod
    def args_from_json(self, j):
        args = super(AsymTest, self).args_from_json(j)
        args['cc2_delay'] = j['cc2_delay']
        return args


parser = argparse.ArgumentParser(
    description="Tests illustrating TCP Prague's controlled RTT dependence.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    epilog='If neither --execute-tests nor --plot are set, both of these steps will run'
)
parser.add_argument('-x', '--execute-tests', help='Execute the tests',
                    action='store_true', default=False)
parser.add_argument('-p', '--plot', help='Plot results', action='store_true',
                    default=False)
parser.add_argument('-o', '--open-plots', help='Open the plots',
                    action='store_true', default=False)
parser.add_argument('-c', '--cwd',
                    help='Set working directory to save/load results',
                    type=pathlib.Path, default=pathlib.Path('.'))
parser.add_argument('-i', '--interval',
                    help='Switch base RTT every @interval s',
                    type=int, default=Test.INTERVAL)
parser.add_argument('-a', '--aqm',
                    help='The AQM (and parameters) to use at the bottleneck',
                    type=str, default=Test.AQM)
parser.add_argument('-b', '--bandwidth',
                    help='Bottleneck Bandwidth [Mbit]. Note that this bandwidth'
                    ' MUST be high-enough to sustain flows operating at min-cwnd'
                    ' and very low (few us) base RTT, i.e., 2MSS at 600us'
                    ' requires 40Mbit/s for a single flow, hence'
                    ' rate-equivalence requires a bottleneck of at least'
                    ' 80Mbit/s',
                    type=int, default=Test.MAX_BW)
parser.add_argument('-d', '--delays',
                    help='Base RTTs to use',
                    type=int, default=Test.DELAYS, nargs='+')
parser.add_argument('-I', '--ignore_modules',
                    help='Do not try to load required kernel modules',
                    action='store_true', default=False)
args = parser.parse_args()

Test.DATA_DIR = args.cwd
Test.INTERVAL = args.interval
Test.DELAYS = args.delays
Test.MAX_BW = args.bandwidth
Test.AQM = args.aqm
log.info("Test configured with DATA_DIR=%s, INTERVAL=%s, DELAYS=%s, MAX_BW=%s,"
         " AQM=%s", Test.DATA_DIR, Test.INTERVAL, Test.DELAYS, Test.MAX_BW,
         Test.AQM)

sp.check_call(['mkdir', '-p', str(Test.DATA_DIR)])

# if neither -x nor -p, defaults to all
if args.execute_tests or not args.plot:
    if not args.ignore_modules:
        try:
            sp.check_call(['sudo', 'modprobe', 'tcp_prague'])
            sp.check_call(['sudo', 'modprobe', 'sch_dualpi2'])
        except sp.CalledProcessError as e:
            log.exception('Failed to load the required kernel modules')
            sys.exit()
    else:
        log.info('Skipping kernel module check, this might prevent from running'
                 ' experiments!')

    testplan = [Test(Prague, Cubic),
                Test(PragueRTTIndep, Cubic),
                Test(PragueRTTIndepAdditive, Cubic),
                AsymTest(15, PragueRTTIndep, Cubic)]
    Test.save_config(testplan)

    for t in testplan:
        t.run_test()

    try:
        sp.check_call([Test.SCRIPT, '-c'])
    except sp.CalledProcessError as e:
        log.exception('Failed to tear down the virtual network')
        sys.exit()
else:
    log.info('Skipping run_test()')

if args.plot or not args.execute_tests:
    testplan = Test.load_config()
    for t in testplan:
        t.plot()
    Test.gen_report(testplan)
else:
    log.info('Skipping plot()')

if args.open_plots:
    testplan = Test.load_config()
    for t in testplan:
        if (os.fork() == 0):
            sp.call(['xdg-open', t.fig_name()],
                    stdout=sp.DEVNULL, stderr=sp.DEVNULL)
