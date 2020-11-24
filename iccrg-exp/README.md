This [directory](.) holds the results and scripts used to generate them (virtual network, metric collection, plotting)
that were presented during the ICCRG meeting held during IETF-109 on Nov. 20 2020.

The [testrunner.py] script is the one responsible to drive the whole experiment. E.g. `./python testrunner.py --help` for usage instructions.
The full set of results is spread over [results/](results) (raw data) and [results/plots](results/plots) (plots (sic)).

In particular, the graphs show side by side the throughput timeseries over the experiment, as well as the per-packet queue delay.

## Dependencies

These scripts must run on a kernel supporting TCP Prague, such as those that
can be built from the [L4S kernel tree](https://github.com/L4STeam/linux). Note that you can grab pre-built images in the artifacts of the "Actions" tab. If you build your own kernel, make sure to enable the support for network namespaces, veth pairs, virtual bridge, ...

Additionally, the host machine should have installed:
* python3
* matplotlib (e.g., `apt-get install python3-matplotlib`)
* iperf3 (e.g., `apt-get install iperf3`)
* libpcap and its development header (e.g., `sudo apt-get install libpcap-dev libpcap`)
