This repository hosts various resources about L4S, and the existing
implementations.

See the general [L4S Landing Page](https://riteproject.eu/dctth) for various resources around L4S.

# Components

All various components required to test L4S are under a [common Github umbrella](https://github.com/L4Steam). In particular:
- [Linux kernel](https://gitub.com/L4Steam/linux) containing the necessary patches
enabling TCP prague and the dualpi2 qdisc. The repository also provides
pre-packaged debian binaries to ease up experimentation.
- [iproute2](https://github.com/L4steam/iproute2) user-space utilities to manage
the dualpi2 qdisc and query the TCP Prague statistics.
- [GUI (l4sdemo)](https://github.com/L4steam/l4sdemo) that enables to dynamically interact with a testbed,
visualising per-packet latencies, ... as well as support script to automate more
in-depth testing.
- [Virtual machine provisioning scripts] to automate test VM creation.
- [SCReAM](https://github.com/L4Steam/scream), a mobile optimized congestion
control algorithm which supports L4S.

# Experiments

[TCP Prague controlled RTT dependence](rtt-independence)

[ECT(1) tests](ect1-tests)

[DualPI2 overload experiments](overload-experiments)

[ICCRG experiments (21/11/2020)](iccrg-exp)
