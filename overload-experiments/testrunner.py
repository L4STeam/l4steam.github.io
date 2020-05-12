#!/usr/bin/python3
# SPDX-License-Identifier: BSD-3 Clause
__copyright__ = 'Copyright (C) 2020, Nokia'

import argparse
import io
import itertools
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

US_PER_S = 1_000_000


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


def title_to_md_link(string):
    del_chars = set((')', '(', ':'))
    tr = {' ': '-'}
    return ''.join(tr.get(s, s).lower() for s in string if s not in del_chars)


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

    @classmethod
    def as_json_args(cls):
        return {}


class Cubic(CCA):
    NAME = 'cubic'
    COLOR = 'orange'

    @classmethod
    def configure(cls):
        return cls

    @classmethod
    def pretty_name(cls):
        return cls.NAME

    @classmethod
    def name(cls):
        return cls.__name__


class Prague(Cubic):
    NAME = 'prague'
    COLOR = 'blue'
    PARAMS = {
       # 'rtt_scaling': '0',
       # 'rtt_target': '15000',
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
        if cls.PARAMS:
            return '%s (%s)' % (cls.NAME, ','.join(('%s=%s' % (k, v)
                                                    for k, v in cls.PARAMS.items())))
        return cls.NAME


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


class UDP(Cubic):
    _NAME = 'udp'
    KEY = 'DO_UDP'
    COLOR = '#31a354'
    HOST = 's3'

    def __init__(self, bw='50M'):
        self.bw = bw

    @property
    def NAME(self):
        return '%s_%s' % (self._NAME, self.bw)

    def pretty_name(self):
        return '%s (%s)' % (self._NAME, self.bw)

    def as_json_args(self):
        return {'bw': self.bw}

    def env(self):
        return {self.KEY: self.bw}

    def __str__(self):
        return self.NAME
    __repr__ = __str__


class UDP_ECT0(UDP):
    _NAME = 'udp-ect0'
    COLOR = '#542788'
    KEY = 'DO_UDP_ECT0'
    HOST = 's4'


class UDP_ECT1(UDP):
    _NAME = 'udp-ect1'
    COLOR = '#dd1c77'
    KEY = 'DO_UDP_ECT1'
    HOST = 's5'


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
    DELAY = 20 # ms
    BW_SCALE = 1_000_000  # Mb
    MAX_BW = 100
    AQM = 'dualpi2'
    DURATION = 20  # s
    _CFG = "test_cfg.json"

    def __init__(self, cc1=Prague, cc2=Cubic, load=[],
                 env={'DO_TCP_S1_C1': "yes", 'DO_TCP_S2_C2': "yes"}):
        self.cc1 = cc1
        self.cc2 = cc2
        self.load = load
        self.env = self.build_env(env)

    @classmethod
    def cfg_file(cls):
        return cls.DATA_DIR / cls._CFG

    @classmethod
    def save_config(cls, testplan):
        with open(cls.cfg_file(), 'w') as f:
            json.dump(dict(data_dir=str(cls.DATA_DIR),
                           delay=cls.DELAY,
                           max_bw=cls.MAX_BW,
                           aqm=cls.AQM,
                           duration=cls.DURATION,
                           testplan=[t.as_json() for t in testplan]),
                      f)

    def as_json(self):
        return dict(test_type=self.__class__.__name__,
                    env=self.env, cc1=self.cc1.as_json(),
                    cc2=self.cc2.as_json(),
                    load=[{'name': l.as_json(),
                           'args': l.as_json_args()} for l in self.load])

    @classmethod
    def args_from_json(cls, j):
        return dict(cc1=CCA.get(j['cc1']), cc2=CCA.get(j['cc2']),
                    load=[CCA.get(l['name'])(**l['args']) for l in j['load']],
                    env=j['env'])

    @classmethod
    def from_json(cls, j):
        obj = cls(**cls.args_from_json(j))
        return obj

    @classmethod
    def load_config(cls):
        test_types = get_all_subclasses(cls)
        test_types[cls.__name__] = cls
        CCA.discover_subclasses()

        with open(cls.cfg_file(), 'r') as f:
            data = json.load(f)
        try:
            cls.DELAY = float(data['delay'])
            cls.MAX_BW = int(data['max_bw'])
            cls.AQM = data['aqm']
            cls.DURATION = data['duration']
            return [test_types[t['test_type']].from_json(t)
                    for t in data['testplan']]
        except KeyError as e:
            log.exception('Corrupted test config file')
            sys.exit()

    def configure(self):
        self.cc2.configure()
        self.cc1.configure()
        for l in self.load:
            self.env.update(l.env())

    def build_env(self, env):
        base = {
            'AQM': self.AQM,
            'RATE': '%dMbit' % self.MAX_BW,
            'DELAY': '%fms' % self.DELAY,
            'C1_CCA': self.cc1.NAME,
            'C2_CCA': self.cc2.NAME,
            'TIME': '%d' % self.DURATION,
            'LOG_PATTERN': self.log_pattern,
            'DATA_DIR': str(self.DATA_DIR)
        }
        base.update(env)
        return base

    def run_test(self):
        log.info('Running %s vs %s with load %s', self.cc1.pretty_name(),
                 self.cc2.pretty_name(), [l.pretty_name() for l in self.load])
        self.configure()
        self.env.update(os.environ)

        process = sp.Popen([self.SCRIPT, '-cst'], env=self.env)
        # Wait for iperf to stop/flush
        process.wait()

    @property
    def log_pattern(self):
        return '%s_%s_%s'% (self.cc1.__name__, self.cc2.__name__,
                           '_'.join(l.NAME for l in self.load))

    def process_qdelay_data(self, host):
        results = self.DATA_DIR / ('qdelay_%s_%s.qdelay' % (
            host, self.env['LOG_PATTERN']))
        try:
            with open(results, 'r') as input_data:
                data = json.load(input_data)
        except (IOError, json.JSONDecodeError) as e:
            log.exception("Could not load the qdelay results for client '%s'",
                          host)
            sys.exit()
        delay = np.empty(len(data['results']))
        t = np.empty(len(data['results']))
        for i, d in enumerate(data['results']):
            delay[i] = d['delay-us'] / 1000.0
            t[i] = float(d['ts-us']) / US_PER_S
        return t[0], delay, t

    def process_bw_data(self, client, suffix=''):
        results = self.DATA_DIR / (
            'iperf_%s_%s%s.json' % (client, self.env['LOG_PATTERN'],
                                    '_%s' % suffix if suffix else ''))
        try:
            with open(results, 'r') as input_data:
                data = json.load(input_data)
        except (IOError, json.JSONDecodeError) as e:
            log.exception("Could not load the bandwidth results for client '%s'",
                          client)
            sys.exit()
        throughput = np.empty(len(data['intervals']))
        t = np.empty(len(data['intervals']))
        base = data['start']['timestamp']['timesecs']
        for i, d in enumerate(data['intervals']):
            throughput[i] = d['streams'][0]['bits_per_second'] / self.BW_SCALE
            t[i] = base + d['streams'][0]['end']
        return base, throughput, t

    @property
    def cc1_name(self):
        return self.cc1.pretty_name()

    @property
    def cc2_name(self):
        return self.cc2.pretty_name()

    def plot_qdelay(self, ax):
        ax.set_ylabel('Queue delay [ms]')
        ax.set_yscale('symlog')

        series = [('s1', self.cc1), ('s2', self.cc2)]
        series.extend([(l.HOST, l) for l in self.load])
        time_base = set()
        for host, cc in series:
            log.info('.. qdelay for client=%s', host)
            base, delay, t = self.process_qdelay_data(host)
            time_base.add(base)
            ax.plot(t, delay, label=cc.pretty_name(), color=cc.COLOR, alpha=.9,
                    linewidth=1, linestyle='dotted')
        ax.set_yticks([0, 1, 10, 30])
        ax.set_yticklabels([0, 1, 10, 30])
        log.info(time_base)
        return min(time_base)

    def plot_bw(self, ax):
        ax.set_ylabel('Throughput [Mbps]')
        ax.set_ylim(-1, self.MAX_BW)
        ax.set_yticks([0, self.MAX_BW / 4, self.MAX_BW / 2,
                       self.MAX_BW * 3 / 4, self.MAX_BW])

        time_base = set()

        for cc, data, name in ((self.cc1, 'c1', self.cc1_name),
                               (self.cc2, 'c2', self.cc2_name)):
            log.info('.. bandwidth for client=%s', data)
            color = cc.COLOR
            base, bw, t = self.process_bw_data(data)
            time_base.add(base)
            avg = avg_series(bw, t, 1.0)
            ax.plot(t, avg, label=name,
                     color=color, alpha=.8, linewidth=1)
        for l in self.load:
            log.info('.. for UDP load=%s', l.pretty_name())
            color = l.COLOR
            base, bw, t = self.process_bw_data(l.HOST, l.NAME)
            time_base.add(base)
            avg = avg_series(bw, t, 1.0)
            ax.plot(t, avg, label=l.pretty_name(),
                     color=color, alpha=.8, linewidth=1)

        ax.legend()
        log.info(time_base)
        return min(time_base)

    def plot(self):
        log.info('Plotting %s vs %s with load %s', self.cc1.pretty_name(),
                 self.cc2.pretty_name(), self.load)

        fig, (ax, delay_ax) = plt.subplots(
            nrows=2, figsize=(10, 6), sharex=True,
            gridspec_kw={ 'hspace': 0, 'height_ratios': [5, 1], })

        time_base = self.plot_bw(ax)
        time_base = min(self.plot_qdelay(delay_ax), time_base)

        ax.label_outer()
        delay_ax.label_outer()
        delay_ax.set_xlabel('Time [s]')
        ax.set_xlim(time_base, time_base + self.DURATION)
        delay_ax.set_xlim(time_base, time_base + self.DURATION)
        ticks = [i * self.DURATION / 8 for i in range(9)]
        delay_ax.set_xticks([time_base + t for t in ticks])
        delay_ax.set_xticklabels([str(t) for t in ticks])

        fig.savefig(self.fig_path('pdf'))
        fig.savefig(self.fig_path('png'), transparent=False, dpi=300)

        plt.close(fig)

    def fig_name(self, ext='pdf'):
        return '%s.%s' % (self.log_pattern, ext)

    def fig_path(self, ext='pdf'):
        return str(self.DATA_DIR / self.fig_name(ext))

    @classmethod
    def gen_report(cls, testplan):
        with open(cls.DATA_DIR / 'README.md', 'w') as f:
            f.write("""
# Description

Tests run on a `{MAX_BW}Mbps` bottleneck, with a `{DELAY}ms` base RTT.

AQM in use: `{AQM}`

See the [test config file]({cfg}).

""".format(MAX_BW=cls.MAX_BW, cfg=cls._CFG, DELAY=cls.DELAY,
           AQM=cls.AQM))

            headings = ["Test-%s: %s vs %s with a background load of %s" % (
                i + 1, t.cc1.__name__, t.cc2.__name__, ' and '.join(l.pretty_name() for l in t.load))
                        for i, t in enumerate(testplan)]
            for h in headings:
                f.write(" * [{h}](#{link})\n".format(h=h,
                                                     link=title_to_md_link(h)))

            for t, h in zip(testplan, headings):
                f.write("""
# {h}

CCA for flow (1): {cc1}

CCA for flow (2): {cc2}

Background load: {load}

![Result graph]({graph})

[Go back to index](#description)
""".format(h=h, cc1=t.cc1.pretty_name(), cc2=t.cc2.pretty_name(),
           load=', '.join(l.pretty_name() for l in t.load),
           graph=t.fig_name('png')))



parser = argparse.ArgumentParser(
    description="Tests exploring dualpi2 overload behavior.",
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
parser.add_argument('-a', '--aqm',
                    help='The AQM (and parameters) to use at the bottleneck',
                    type=str, default=Test.AQM)
parser.add_argument('-b', '--bandwidth',
                    help='Bottleneck Bandwidth [Mbit]',
                    type=int, default=Test.MAX_BW)
parser.add_argument('-d', '--delay',
                    help='Base RTT to use',
                    type=int, default=Test.DELAY)
parser.add_argument('-I', '--ignore_modules',
                    help='Do not try to load required kernel modules',
                    action='store_true', default=False)
args = parser.parse_args()

Test.DATA_DIR = args.cwd
Test.DELAY = args.delay
Test.MAX_BW = args.bandwidth
Test.AQM = args.aqm
log.info("Test configured with DATA_DIR=%s, DELAY=%s, MAX_BW=%s, AQM=%s",
         Test.DATA_DIR, Test.DELAY, Test.MAX_BW, Test.AQM)

sp.check_call(['mkdir', '-p', str(Test.DATA_DIR)])

# if neither -x nor -p, defaults to all
if args.execute_tests or not args.plot:
    if not args.ignore_modules:
        try:
            sp.check_call(['sudo', 'modprobe', 'tcp_prague'])
            sp.check_call(['bash', '-c', 'cd %s && make' % str(Test.CWD / 'modules')])
            sp.check_call(['sudo', 'make', '-C', str(Test.CWD / 'modules'), 'load'])
        except sp.CalledProcessError as e:
            log.exception('Failed to load the required kernel modules')
            sys.exit()
    else:
        log.info('Skipping kernel module check, this might prevent from running'
                 ' experiments!')

    testplan = []
    loads = [UDP, UDP_ECT0, UDP_ECT1]
    for bw in ['10M', '20M', '50M', '75M', '100M']:
        for i in range(len(loads)):
            for load in itertools.combinations(loads, i + 1):
                testplan.append(Test(Prague, Cubic, [l(bw) for l in load]))
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
