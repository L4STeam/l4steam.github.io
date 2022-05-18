# Disproof of 'Throughput Bonus' or 'Fast-Lane' Objection

## Background

* The [objection](https://sce.dnsmgr.net/downloads/L4S-WGLC2-objection-details.pdf) (p4-5) claimed the DualQ offers a 'fast-lane' or 'throughput bonus' and  
   "the bonus is easily exploited by unscrupulous senders without disabling congestion control"  
* These claims were based on:
  * a single experiment run with
  * no control experiment to check whether the alleged 'fast lane' was any faster than the other lane
* The following experiments aim to reproduce the objectors' experiment precisely 
  * and to add control experiments

## Experiment A. 2 CUBIC flows; 1 "tweaked" flow joins after 10s



* Does not reproduce objection
* Tweaked flow gets significantly smaller  capacity share (blue), not larger

## Experiment B. Tweaked flow then also made unresponsive

* Reproduces objection very closely 
  * but objection claimed cong. ctrl was not disabled
* Tweaked flow now gets 40Mbps (blue)
  * as expected for 40Mbps paced unrespns've flow

plot from objection for comparison

## Control experiment C.: Tweaked flow unresponsive but ECT(0)

* Proves thru'put advantage is due to unresponsiveness, not DualPI2
* because tweaked flow (blue) gets same advantage in either queue

## Summary

* No evidence for objectors' 'fast-lane' claim by reproducing their experiment
* The result can be reproduced v closely by suppressing congestion control
  * But objectors stated "bonus is easily exploited ... without disabling congestion control"
  * Objectors' experiment was likely faulty, and somehow suppressed congestion control 
* Our experiments include a control run 
  * Claimed 'fast lane' is no faster than the other lane
  * Dual Queue Coupled AQM meets its stated goal of not allowing unresponsive flows to cause more harm to existing traffic than in a single queue
    * unresponsive thru'put: same in either queue
    * unresponsive delay: lower in L than C queue, but not at the expense of anyone else's delay
  
  
---
# Details In-Depth 

## Control experiment D.: Tweaked flow ECT(0) and responsive

* Proves 40Mbps pacing is only a cap
* Because tweaked flow behaves:
  * as normal, given stable rate below 40Mb/s

## Experiment details

All nodes: 
* Ubuntu 18.04.4 LTS
* Linux kernel 5.10.31-3cc3851880a1-prague-37
* iproute2-5.9.0
* Commit ID: testing/[6e042bcd4158](https://github.com/L4STeam/linux/commit/6e042bcd4158)

## Inside experiment A: 2 CUBIC flows; 1 "tweaked"

* Lower plot explains low thru'put of tweaked flow, due to its response to deliberately aggressive coupled marking (blue) instead of the Classic marking (red) intended for CUBIC
* zero native L4S marking (green dashed)

## Inside experiment B: Tweaked and unresponsive flow

* Lower plot shows that the unresponsive L flow squeezes the C flow into less capacity by causing 
  * higher C congestion (red) and 
  * in turn, higher coupled L congestion (blue) which it ignores
* Still zero native L4S marking (green dashed)

---
Chia-Yu Chang (Nokia Bell Labs), [Koen De Schepper](https://www.bell-labs.com/about/researcher-profiles/koende_schepper/) (Nokia Bell Labs) and [Bob Briscoe](https://bobbriscoe.net/) (Independent)
