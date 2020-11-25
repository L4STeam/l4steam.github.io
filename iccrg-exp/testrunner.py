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

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

log.basicConfig(level=log.INFO)

plt.style.use('ggplot')


US_PER_S = 1_000_000

font = {'family' : 'normal',
        'size'   : 14}

matplotlib.rc('font', **font)


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
    ECN = 0
    EXTRA_RTT = 0

    @classmethod
    def discover_subclasses(cls):
        cls.ALL = get_all_subclasses(cls)

    @classmethod
    def get(cls, name):
        if not name:
            return None
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
    AQM = 'fq_codel_tst'
    AQM_NAME = 'codel'
    ECN = 1

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
    AQM = AQM_NAME = 'dualpi2'
    ECN = 3
    PARAMS = {
       # 'rtt_scaling': '1',
       # 'rtt_target': '25000',
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
            return '%s (%s)' % (
                super().pretty_name(), ','.join(('%s=%s' % (k, v)
                                                 for k, v in cls.PARAMS.items())))
        return super().pretty_name()


class Prague0d5(Prague):
    EXTRA_RTT = 0.5


class Cubic0d5(Cubic):
    EXTRA_RTT = 0.5


class Prague1(Prague):
    EXTRA_RTT = 1
    COLOR = 'magenta'


class Cubic1(Cubic):
    EXTRA_RTT = 1
    COLOR = 'gold'


class Prague10(Prague):
    EXTRA_RTT = 10
    COLOR = 'indigo'


class Cubic10(Cubic):
    EXTRA_RTT = 10
    COLOR = 'darkgoldenrod'


class Prague30(Prague):
    EXTRA_RTT = 30
    COLOR = 'cornflowerblue'


class Cubic30(Cubic):
    EXTRA_RTT = 30
    COLOR = 'tomato'


class DCTCP(Cubic):
    NAME = 'dctcp'
    COLOR = 'green'
    AQM = AQM_NAME = 'dualpi2'
    ECN = 0


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
    PLOT_SUBDIR = DATA_DIR / 'plots'
    BW_SCALE = 1_000_000  # Mb
    AQM = 'dualpi2'
    DURATION = 40  # s
    _CFG = "test_cfg.json"

    @classmethod
    def set_DATA_DIR(cls, d):
        cls.DATA_DIR = d
        cls.PLOT_SUBDIR = d / 'plots'

    def __init__(self, cc1=Prague, cc2=[], bw=100, rtt=20, env={}, title=''):
        self.cc1 = cc1
        self.cc2 = cc2
        self.bw = bw
        self.rtt = rtt
        self.env = self.build_env(env)
        self.title = title
        os.makedirs(self.PLOT_SUBDIR, exist_ok=True)

    @classmethod
    def cfg_file(cls):
        return cls.DATA_DIR / cls._CFG

    @classmethod
    def save_config(cls, testplan):
        with open(cls.cfg_file(), 'w') as f:
            json.dump(dict(data_dir=str(cls.DATA_DIR),
                           aqm=cls.AQM,
                           duration=cls.DURATION,
                           testplan=[t.as_json() for t in testplan]),
                      f)

    def as_json(self):
        return dict(test_type=self.__class__.__name__,
                    env=self.env, cc1=self.cc1.as_json(), title=self.title,
                    cc2=[cc.as_json() for cc in self.cc2], bw=self.bw, rtt=self.rtt)

    def enumerate_cc2(self):
        for i, cc in enumerate(self.cc2):
            i += 2
            yield i, cc

    @property
    def cc2_names(self):
        return str(tuple(cc.pretty_name() for cc in self.cc2))

    @classmethod
    def args_from_json(cls, j):
        return dict(cc1=CCA.get(j['cc1']), cc2=[CCA.get(cc) for cc in j['cc2']],
                    bw=j.get('bw',100), rtt=j.get('rtt',20),
                    title=j.get('title',''), env=j['env'])

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
            cls.AQM = data['aqm']
            cls.DURATION = data['duration']
            return [test_types[t['test_type']].from_json(t)
                    for t in data['testplan']]
        except KeyError as e:
            log.exception('Corrupted test config file')
            sys.exit()

    def configure(self):
        self.cc1.configure()
        for cc in self.cc2:
            cc.configure()

    def build_env(self, env):
        base = {
            'AQM': self.cc1.AQM,
            'RATE': '%dMbit' % self.bw,
            'DELAY': '%gms' % self.rtt,
            'CC1_CCA': self.cc1.NAME,
            'CC1_ECN': str(self.cc1.ECN),
            'CC1_DELAY': '%gms' % self.cc1.EXTRA_RTT,
            'TIME': '%d' % self.DURATION,
            'LOG_PATTERN': self.log_pattern,
            'DATA_DIR': str(self.DATA_DIR),
            'HOST_PAIRS': str(len(self.cc2) + 1)
        }
        base.update(env)
        for i, cc in self.enumerate_cc2():
            base['CC%d_CCA' % i] = cc.NAME
            base['CC%d_ECN' % i] = str(cc.ECN)
            base['CC%d_DELAY' % i] = '%gms' % cc.EXTRA_RTT
        return base

    def run_test(self):
        log.info('Running %s vs %s at %dMbit/%gms', self.cc1.pretty_name(),
                 self.cc2_names, self.bw, self.rtt)
        self.configure()
        self.env.update(os.environ)

        process = sp.Popen([self.SCRIPT, '-cst'], env=self.env)
        # Wait for iperf to stop/flush
        process.wait()

    @property
    def log_pattern(self):
        return '%s_%s_%s_%s'% (self.cc1.__name__,
                            '_'.join(cc.__name__ for cc in self.cc2),
                            self.bw, self.rtt)

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

    def process_bw_data(self, client, time_base, suffix=''):
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
        throughput = np.empty(len(data['intervals']) + 1)
        t = np.empty(len(data['intervals']) + 1)
        throughput[0] = 0
        t[0] = time_base
        for i, d in enumerate(data['intervals']):
            throughput[i+1] = d['streams'][0]['bits_per_second'] / self.BW_SCALE
            t[i+1] = time_base + d['streams'][0]['end']
        return throughput, t

    def plot_qdelay(self, ax):
        ax.set_ylabel('Queue delay [ms]')

        series = [('s1', self.cc1)]
        for i, cc in self.enumerate_cc2():
            series.append(('s%d' % i, cc))
        time_base = set()
        for host, cc in series:
            log.info('.. qdelay for client=%s', host)
            base, delay, t = self.process_qdelay_data(host)
            time_base.add(base)
            ax.plot(t, delay, label=cc.pretty_name(), color=cc.COLOR, alpha=.9,
                    linewidth=.3) #, linestyle='dotted')
        ticks = sorted([0, 1, 5, 15])
        ax.set_yticks(ticks)
        ax.set_yticklabels(ticks)
        return min(time_base)

    def legend(self, cc):
        return '%s%s@%dMbps/%gms/%s' % (cc.pretty_name(),
                                          ' with ECN' if cc.ECN == 1 else '',
                                          self.bw, self.rtt + cc.EXTRA_RTT,
                                          self.cc1.AQM_NAME)

    def plot_bw(self, ax, time_base):
        ax.set_ylabel('Throughput [Mbps]')
        ax.set_ylim(-1, self.bw)
        ax.set_yticks([0, self.bw / 4, self.bw / 2,
                       self.bw * 3 / 4, self.bw])

        series = [(self.cc1, 'c1', self.legend(self.cc1))]
        for i, cc in self.enumerate_cc2():
            series.append((cc, 'c%d' % i, self.legend(cc)))
        for cc, data, name in series:
            log.info('.. bandwidth for client=%s', data)
            color = cc.COLOR
            bw, t = self.process_bw_data(data, time_base)
            avg = avg_series(bw, t, 1.0)
            ax.plot(t, avg, label=name,
                     color=color, alpha=.8, linewidth=1)
        ax.legend()

    def plot(self):
        log.info('Plotting %s vs %s at %dMbit/%gms', self.cc1.pretty_name(),
                 self.cc2_names,
                 self.bw, self.rtt)

        fig, (ax, delay_ax) = plt.subplots(
            nrows=2, figsize=(10, 6), sharex=True,
            gridspec_kw={ 'hspace': .1, 'height_ratios': [5, 5], })

        time_base = self.plot_qdelay(delay_ax)
        self.plot_bw(ax, time_base)

        ax.label_outer()
        delay_ax.label_outer()
        delay_ax.set_xlabel('Time [s]')
        ax.set_xlim(time_base, time_base + self.DURATION)
        delay_ax.set_xlim(time_base, time_base + self.DURATION)
        ticks = [i * self.DURATION / 8 for i in range(9)]
        delay_ax.set_xticks([time_base + t for t in ticks])
        delay_ax.set_xticklabels([str(t) for t in ticks])
        if self.title:
            fig.suptitle(self.title)

        fig.savefig(self.fig_path('pdf'))
        fig.savefig(self.fig_path('png'), transparent=False, dpi=300)

        plt.close(fig)

    def fig_name(self, ext='pdf'):
        return '%s.%s' % (self.log_pattern, ext)

    def fig_path(self, ext='pdf'):
        return str(self.PLOT_SUBDIR / self.fig_name(ext))

    @classmethod
    def gen_report(cls, testplan):
        with open(cls.PLOT_SUBDIR / 'README.md', 'w') as f:
            f.write("""
# Description

See the [test config file]({cfg}).

""")

            headings = ["Test-%s: %s vs %s at %dMbit/%gms" % (
                i + 1, t.cc1.__name__, [cc.__name__ for cc in t.cc2],
                t.bw, t.rtt) for i, t in enumerate(testplan)]
            for h in headings:
                f.write(" * [{h}](#{link})\n".format(h=h,
                                                     link=title_to_md_link(h)))

            for t, h in zip(testplan, headings):
                f.write("""
# {h}

RTT: {rtt}ms

BW: {bw}Mbit

AQM: {aqm}

CCA for flow (1): {cc1}
""".format(rtt=t.rtt, bw=t.bw, aqm=t.cc1.AQM, h=h, cc1=t.cc1.pretty_name()))
                for i, cc in t.enumerate_cc2():
                    f.write('CCA for flow (%d): %s' % (i, cc.pretty_name()))
                f.write("""
![Result graph]({graph})

[Go back to index](#description)
""".format(graph=t.fig_name('png')))


def gen_testplan():
    testplan = []
    # Basic 1 flow test to show sawtooth
    for bw in [20, 100, 500]:
        for rtt in [5, 20, 40, 80]:
                for cc in (Prague, Cubic):
                    testplan.append(Test(cc, bw=bw, rtt=rtt))
    # Show DCTCP's failures
    testplan.append(Test(DCTCP, bw=100, rtt=20))
    # Show RTT dep behavior
    testplan.append(Test(Prague0d5, cc2=[Prague1, Prague10, Prague30],
                         bw=400, rtt=0, ))
    testplan.append(Test(Cubic0d5, cc2=[Cubic1, Cubic10, Cubic30],
                         bw=400, rtt=0))
    # Show co-existence
    testplan.append(Test(Cubic, cc2=[Prague],
                         bw=100, rtt=20))
    Cubic.ECN = 0  # work around for our statically forced any_ect on dualpi2
    testplan.append(Test(Prague, cc2=[Cubic],
                         bw=100, rtt=20))
    Test.save_config(testplan)
    return testplan


parser = argparse.ArgumentParser(
    description="Tests showing basic throughput/qdelay measurements",
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
                    type=pathlib.Path, default=pathlib.Path('results'))
parser.add_argument('-I', '--ignore_modules',
                    help='Do not try to load required kernel modules',
                    action='store_true', default=False)
parser.add_argument('-g', '--generate-testplan',
                    help='Generate and save the testplan',
                    action='store_true', default=False)
args = parser.parse_args()

Test.set_DATA_DIR(args.cwd)
log.info("Test configured with DATA_DIR=%s", Test.DATA_DIR)

sp.check_call(['mkdir', '-p', str(Test.DATA_DIR)])

if args.generate_testplan:
    gen_testplan()

# if neither -x nor -p, defaults to all
if args.execute_tests or not args.plot:
    if not args.ignore_modules:
        try:
            sp.check_call(['sudo', 'modprobe', 'tcp_prague'])
            sp.check_call(['bash', '-c', 'cd %s && make' % str(Test.CWD / 'modules')])
            sp.check_call(['sudo', 'bash', '-c', 'cd %s && make load' % str(Test.CWD / 'modules')])
        except sp.CalledProcessError as e:
            log.exception('Failed to load the required kernel modules')
            sys.exit()
    else:
        log.info('Skipping kernel module check, this might prevent from running'
                 ' experiments!')

    testplan = gen_testplan()
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
