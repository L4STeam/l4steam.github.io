# SCE-L4S ECT(1) Test Results

This directory contains a re-run of the ECT(1) tests performed at [@heistp/sce-l4s-ect1](https://gitub.com/heistp/sce-l4s-ect1). More precisely, it provides the test results for L4S, after fixing a bug reported in the original set of experiments (see [commit#xxx](https://github.con/L4STeam/linux)).

In the next sections, the text of the README is _unchanged_ from its original version, hence might no longer match what is shown in the displayed graphs.

## Table of Contents

1. [Key Findings](#key-findings)
2. [Elaboration on Key Findings](#elaboration-on-key-findings)
3. [Full Results](#full-results)
   1. [Scenario 1: One Flow](#scenario-1-one-flow)
   2. [Scenario 2: Two Flow Competition](#scenario-2-two-flow-competition)
   3. [Scenario 3: Bottleneck Shift](#scenario-3-bottleneck-shift)
   4. [Scenario 4: Capacity Reduction](#scenario-4-capacity-reduction)
   5. [Scenario 5: WiFi Burstiness](#scenario-5-wifi-burstiness)
   6. [Scenario 6: Jitter](#scenario-6-jitter)
5. [Appendix](#appendix)
   1. [Test Setup](#test-setup)

## Key Findings

1. In the L4S reference implementation, RFC 3168 bottleneck detection is
   unreliable in at least the following ways:
   *  *False negatives* (undetected RFC 3168 bottlenecks) occur with tightened
      AQM settings for Codel, RED and PIE, resulting in the starvation
      of competing traffic (in [Scenario 2](#scenario-2-two-flow-competition),
      see results for the aforementioned qdiscs).
   *  *False positives* (L4S bottlenecks incorrectly identified as RFC 3168)
      occur in the presence of about 2ms or more of jitter, resulting in
      under-utilization (see the L4S results in [Scenario
      6](#scenario-6-jitter)). Further false positives also occur at low
      bandwidths, with the same effect (see [Scenario 1](#scenario-1-one-flow)
      at 5Mbit, with 80ms or 160ms RTT).
   *  *Insensitivity* to the delay-variation signal occurs when packet loss is
      experienced.  If the detection is currently for L4S, it will remain so,
      and likewise for RFC 3168.  This interacts adversely with dropping AQMs.
2. In the L4S reference implementation, packet loss is apparently not treated as
   a congestion signal, unless the detection algorithm has placed it in
   the RFC 3168 compatible mode.  This does not adhere to the principle of
   effective congestion control (for one example, in
   [Scenario 2](#scenario-2-two-flow), see the pfifo results for L4S).
3. *Ultra-low delay*, defined here as queueing delay <= ~1ms, is **not**
   achievable for the typically bursty traffic on the open Internet without
   significant reductions in utilization, and should therefore not be a key
   selection criteria between the two proposals when it comes to the ECT(1)
   codepoint decision (in [Scenario 5](#scenario-5-wifi-burstiness), see
   Prague utilization in L4S results, compared to twin_codel_af utilization with
   Codel's burst-tolerant SCE marking behavior, in the SCE results).
4. Ultra-low delay **is** achievable in the SCE architecture on appropriate
   paths, currently by using DSCP as a classifier to select tightened AQM
   settings (in [Scenario 1](#scenario-1-one-flow), see 50Mbit and 250Mbit cases
   at 20ms RTT).

## Elaboration on Key Findings

Whenever you rely on a heuristic, rather than an explicit signal, you need to establish:
- which cases may result in false-positive detections (defined here as detecting a path as a classic AQM when in fact it is providing L4S signalling),
- which may result in false-negative detections (defined here as failing to recognise a classic AQM as such), and
- what circumstances may result in an unintentional desensitisation of the heuristic.

You also need to determine how severe the consequences of these failures are,
which in this case means checking the degree of unfairness to competing traffic that results, and the impact on the performance
of the L4S flow itself.  This is what we set out to look for.

### Utopia

First, to give some credit, the "classic AQM detection heuristic" does appear to work in some circumstances, as we can see in the following plot:

$(plot_inline "When everything goes well" "l4s-s2-twoflow" "ns-cubic-vs-prague-codel1q-80ms_tcp_delivery_with_rtt.svg")  
*Figure 1*  

When faced with a single-queue Codel or PIE AQM at default parameters, TCP Prague appears to successfully switch into its fallback mode 
and compete with reasonable fairness.  Under good network conditions, it also correctly detects an L4S queue at the 
bottleneck.  It even successfully copes with the tricky case of the bottleneck being changed between DualQ-PI2 and a PIE 
instance with ECN disabled, though it takes several sawtooth cycles to switch back into L4S mode after DualQ-PI2 is restored 
to the path.  We suspect this represents the expected behaviour of the heuristic, from its authors' point of view.

However, we didn't have to expand our search very far to find cases that the heuristic did not cope well with, and some of 
which even appeared to break TCP Prague's congestion control entirely.  That is where our concern lies.

### False Negatives

$(plot_inline "Hunting for the wrong answer" "l4s-s2-twoflow" "ns-cubic-vs-prague-red_150000_-80ms_tcp_delivery_with_rtt.svg")
*Figure 2*  

**False-negative detections are the most serious,** when it comes to maintaining "friendly coexistence" with conventional 
traffic.  We found them in three main areas:
 * Using RED with a limit of 150000, in which the heuristic can oscillate between detection states (see *Figure 2*),
 * Codel and PIE instances tuned for shorter path lengths than default, in which the delay-variance signal that the 
heuristic relies upon is attenuated (see *Figure 3*),
 * Queues which signal congestion with packet-drops instead of ECN marks, including dumb drop-tail FIFOs (both deep and 
shallow) which represent the majority of queues in today's Internet, and PIE with ECN support disabled as it is in 
DOCSIS-3.1 cable modems.  We hypothesise this is due to desensitising of the heuristic in the presence of drops, combined 
with a separate and more serious fault that we'll discuss later.

$(plot_inline "Codel 1q 20ms target" "l4s-s2-twoflow" "ns-cubic-vs-prague-codel1q_20ms_-80ms_tcp_delivery_with_rtt.svg")
*Figure 3*  

The above failure scenarios are not at all exotic, and can be encountered either
by accident, in case of a mis-configuration, or on purpose, when an AQM
is configured to prioritize low delay or low memory consumption over
utilization.  This should cast serious doubt over reliance on this 
heuristic for maintaining effective congestion control on the Internet.  By contrast, SCE flows encountering these same scenarios
behave indistinguishably from normal CUBIC or NewReno flows.

### False Positives

$(plot_inline "Serialisation killer" "l4s-s1-oneflow" "ns-prague-dualpi2-5Mbit-80ms_tcp_delivery_with_rtt.svg")
*Figure 4*

**False-positive detections undermine L4S performance,** as measured by the criteria of maintaining minimum latency and 
maximum throughput on suitably fitted networks.  We found these in three main areas:
 * Low-capacity paths (see *Figure 4* above for a 5Mbps result) introduce enough latency variance via the serialisation delay of individual packets to
trigger the heuristic.  This prevents L4S from using the full capacity of these links, which is especially desirable.
 * Latency variation introduced by bursty and jittery paths, such as those including a simulated wifi segment, also trigger 
the heuristic.  This occurs even if the wifi link is never the overall bottleneck in the path, and the actual bottleneck has 
L4S support.
 * After the bottleneck shifts from a conventional AQM to an L4S one, it takes a number of seconds for the heuristic to 
notice this, usually over several AIMD sawtooth cycles.

L4S flows affected by a false-positive detection will have their throughput cut to significantly less than the true path 
capacity, especially if competing at the bottleneck with unaffected L4S flows.

### Desensitisation

$(plot_inline "Ribbed for nobody's pleasure" "l4s-s2-twoflow" "ns-cubic-vs-prague-pfifo_1000_-80ms_tcp_delivery_with_rtt.svg")
*Figure 5*

**Desensitising** of the heuristic appears to occur in the presence of packet drops (see *Figure 5*).  We are not certain why this would have 
been designed in, although one hypothesis is that it was added to improve behaviour on the "capacity reduction" test we 
presented at an earlier TSVWG interim meeting.  During that test, we noticed that L4S previously exhibited a lot of packet 
loss, followed by a long recovery period with almost no goodput.  Now, there is still a lot of loss at the reduction stage, 
but the recovery time is eliminated.

This desensitising means that TCP Prague remains in the L4S mode when in fact the path produces conventional congestion 
control signals by packet loss instead of ECN marks.  The exponential growth of slow-start means that the first loss is 
experienced before the heuristic has switched over to the classic fallback mode, even if it occurs only after filling an 
80ms path and a 250ms queue (which are not unusual on Internet paths).  However, this would not necessarily be a problem as 
long as packet loss is always treated as a *conventional* congestion signal, and responded to with the conventional 
Multiplicative Decrease.

### Ignoring Packet Loss

Unfortunately, that brings us to the final flaw in TCP Prague's congestion control that we identified.  When in the classic 
fallback mode, TCP Prague does indeed respond to loss in essentially the correct manner.  However when in L4S mode, it 
appears to ignore loss entirely for the purposes of congestion control (see *Figure 6*).  **We repeatably observed full utilisation of the 
receive window in the face of over 90% packet loss.** A competing TCP CUBIC flow was completely starved of throughput; 
exactly the sort of behaviour that occurred during the congestion collapse events of the 1980s, which the AIMD congestion 
control algorithm was introduced to solve.

$(plot_inline "Absolutely Comcastic" "l4s-s2-twoflow" "ns-cubic-vs-prague-pie_noecn_-160ms_tcp_delivery_with_rtt.svg")
*Figure 6*

**This is not effective congestion control.**

### Ultra Low Delay

Foremost in L4S' key goals is "Consistently ultra low latency".  A precise definition of this is difficult to find 
in their documentation, but conversations indicate that they aim to achieve **under 1ms of peak queue delay.**  We consider 
this to be an unachievable goal on the public Internet, due to the jitter and burstiness of real traffic and real Internet 
paths.  Even the receive path of a typical Ethernet NIC has about 1ms of jitter, due to interrupt latency designed in to
reduce CPU load.

Some data supporting this conclusion is [included in the appendix](#typical-internet-jitter), which shows that over even 
modest geographical distances on wired connections, the jitter on the path can be larger than the peak delay L4S
targets.  Over intercontinental distances it is larger still.  But this jitter has to be accommodated in the queue to maintain full 
throughput, which is another stated L4S goal.

To accommodate these real-world effects, the SCE reference implementation defaults to 2.5ms target delay (without the low-latency
PHB), and accepts short-term delay excursions without excessive congestion signalling.

The L4S congestion signalling strategy is much more aggressive, so that encountering this level of jitter causes a severe 
reduction in throughput - all the more so because this also triggers the classic AQM detection heuristic.

The following two plots (*Figure 7* and *Figure 8*) illustrate the effect of adding a simulated wifi link to a typical 80ms Internet path - first with 
an SCE setup, then with an L4S one.  These plots have the same axis scales.  The picture is broadly similar on a 20ms path, too.

$(plot_inline "Wireless SCE" "sce-s5-burstiness" "ns-cubic-sce-twin_codel_af-50Mbit-80ms_tcp_delivery_with_rtt.svg")
*Figure 7*
$(plot_inline "Wireless L4S" "l4s-s5-burstiness" "ns-prague-dualpi2-50Mbit-80ms_tcp_delivery_with_rtt.svg")
*Figure 8*

A larger question might be: what *should* "ultra low delay" be defined as, in an Internet context?  Perhaps we should refer 
to what queuing delay is *typically* observed today.  As an extreme outlier, this author has personally experienced over 40 seconds 
of queue delay, induced by a provisioning shaper at a major ISP.  Most good network engineers would agree that even 4 
seconds is excessive.  A "correctly sized" drop-tail FIFO might reach 400ms during peak traffic hours, when capacity is 
stretched and available bandwidth per subscriber is lower than normal - so let's take that as our reference point.

Compared to 400ms, a conventional AQM might show a 99th-percentile delay of 40ms under sustained load.  We can reasonably 
call that "low latency", as it's comparable to a single frame time of standard-definition video (at 25 fps), and well within the 
preferred jitter buffer dimensions of typical VoIP clients.  So perhaps "ultra low delay" is reasonably defined as an 
order of magnitude better than that, at 4ms; that's comparable to the frame time of a high-end gaming monitor.

Given experience with SCE's default 2.5ms target delay, we think 4ms peak delay is realistically achievable on a good, short 
Internet path with full throughput.  The Codel AQM we've chosen for SCE can already achieve that in favourable 
conditions, while still obtaining reasonable throughput and latency control when conditions are less than ideal.

There is nothing magical about the codepoint used for this signalling; both L4S and SCE should be able to achieve the same 
performance if the same algorithms are applied.  But SCE aims for an achievable goal with the robustness to permit safe 
experimentation, and this may fundamentally explain the contrast in the plots above.

## Full Results

In the following results, the links are named as follows:

- _plot_: the plot svg
- _cli.pcap_: the client pcap
- _srv.pcap_: the server pcap
- _teardown_: the teardown log, showing qdisc config and stats

### Scenario 1: One Flow

$(cli_gen_table s1)

### Scenario 2: Two Flow Competition

$(cli_gen_table s2)

### Scenario 3: Bottleneck Shift

$(cli_gen_table s3)

### Scenario 4: Capacity Reduction

$(cli_gen_table s4)

### Scenario 5: WiFi Burstiness

$(cli_gen_table s5)

### Scenario 6: Jitter

_Note:_ netem jitter params are: total added delay, jitter and correlation

$(cli_gen_table s6)

## Appendix

### Test Setup

The test setup consists of a dumbbell configuration (client, middlebox and
server) for both SCE and L4S. For these tests, all results were produced on a
single physical machine for each using network namespaces.
[Flent](https://flent.org/) was used for all tests.

For L4S, commit
L4STeam/linux@1014c0e45f63
(from Apr 24, 2020) was used.

The single **fl** script performs the following functions:
- updates itself onto the management server and clients
- runs tests (./fl run), plot results (./fl plot) and pushes them to a server
- acts as a harness for flent, setting up and tearing down the test config
- generates this README.md from a template

If there are more questions, feel free to file an
[issue](https://github.com/heistp/sce-l4s-ect1/issues).
