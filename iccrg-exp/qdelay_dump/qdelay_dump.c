/* SPDX-License-Identifier: BSD-3 Clause
 * Copyright (C) 2020, Nokia
 */
#include <arpa/inet.h>
#include <stdio.h>
#include <pcap.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/tcp.h>

#define TESTBED_ANALYZER
typedef uint32_t u32;
#include "../modules/numbers.h"


static char pcap_errbuf[PCAP_ERRBUF_SIZE];
static pcap_t *handle;

#define CAPLEN (sizeof(struct ethhdr) + sizeof(struct iphdr))
#define US_PER_S 1000000L


static void write_header()
{
	fprintf(stdout, "{\"results\":[\n");
}

static void write_entry(uint64_t ts, u32 delay, u32 drop)
{
	static int first = 1;

	fprintf(stdout,
		"%s{\"ts-us\":%lu,"
		"\"delay-us\":%u,"
		"\"drop\":%u}\n", first ? "" : ",", ts, delay, drop);
	first = 0;
}

static void write_close()
{
	fprintf(stdout, "]}\n");
	fflush(stdout);
	fclose(stdout);
}

static void capture_handler(u_char *user, const struct pcap_pkthdr *h,
			    const u_char *bytes)
{
	uint32_t delay, drops;
	struct ethhdr *eth;
	struct iphdr *ip;
	uint16_t id;
	(void)user;

	if (h->caplen < CAPLEN)
		return;

	eth = (struct ethhdr*)bytes;
	if (eth->h_proto != ntohs(ETH_P_IP))
		return;

	ip = (struct iphdr*)(bytes + sizeof(*eth));
	if (ip->version != 4)
		return;

	id = ntohs(ip->id);
	delay = qdelay_decode(id & ((1 << (QDELAY_M + QDELAY_E)) - 1));
	drops = fl2int(id >> (QDELAY_E + QDELAY_M), DROPS_M, DROPS_E);
	write_entry((uint64_t)h->ts.tv_usec + (uint64_t)h->ts.tv_sec * US_PER_S,
		    delay, drops);
}

static void _sig_received(int s)
{
	if (handle)
		pcap_breakloop(handle);
}

static int catch_signals()
{
	struct sigaction act;

	memset(&act, 0, sizeof(act));
	act.sa_handler = _sig_received;

	if (sigaction(SIGINT, &act, NULL) ||
	    sigaction(SIGHUP, &act, NULL)) {
		perror("Cannot register signal handler");
		return EXIT_FAILURE;
	}

	return EXIT_SUCCESS;
}

static int apply_filter(const char *dev, const char *filter)
{
	struct bpf_program fp;
	bpf_u_int32 mask;
	bpf_u_int32 net;

	if (pcap_lookupnet(dev, &net, &mask, pcap_errbuf) == PCAP_ERROR) {
		fprintf(stderr, "Could not find net/mask for dev %s: %s\n",
			dev, pcap_errbuf);
		return EXIT_FAILURE;
	}

	if (pcap_compile(handle, &fp, filter, 1, net) == PCAP_ERROR) {
		fprintf(stderr, "Could not compile pcap filter '%s' for dev %s:"
			"%s\n", filter, dev, pcap_geterr(handle));
		return EXIT_FAILURE;
	}

	if (pcap_setfilter(handle, &fp) == PCAP_ERROR) {
		fprintf(stderr, "Could not set pcap filter on dev %s: %s\n",
			dev, pcap_geterr(handle));
		return EXIT_FAILURE;
	}

	return EXIT_SUCCESS;
}

static int capture(const char *dev, const char *filter)
{
	int err = EXIT_SUCCESS;
	int dlt;

	handle = pcap_open_live(dev, CAPLEN, 0, 1000, pcap_errbuf);
	if (!handle) {
		fprintf(stderr, "Could not open dev %s: %s\n", dev, pcap_errbuf);
		err = EXIT_FAILURE;
		goto out_no_handle;
	}

	dlt = pcap_datalink(handle);
	if (dlt != DLT_EN10MB) {
		fprintf(stderr, "Unexpected datalink header: %s\n",
			pcap_datalink_val_to_name(dlt));
		return EXIT_FAILURE;
	}

	if ((filter && apply_filter(dev, filter)) ||
	    catch_signals()) {
		err = EXIT_FAILURE;
		goto out;
	}

	write_header();
	if (pcap_loop(handle, -1, capture_handler, NULL) == PCAP_ERROR) {
		pcap_perror(handle, "Could not execute the capture loop");
		err = EXIT_FAILURE;
		goto out;
	}

out:
	write_close();
	pcap_close(handle);
out_no_handle:
	return err;
}

int main(int argc, const char **argv)
{
	const char *dev;
	const char *filter;

	if (argc < 2) {
		fprintf(stderr, "Usage: %s INTERFACE <pcap_filter>", *argv);
		return EXIT_FAILURE;
	}
	dev = argv[1];
	filter = argc >= 3 ? argv[2] : NULL;

	return capture(dev, filter);
}
