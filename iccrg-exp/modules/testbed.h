#include <net/inet_ecn.h>
#include "numbers.h"

/* This constant defines whether to include drop/queue level report and other
 * testbed related stuff we only want while developing our scheduler.
 */

struct testbed_metrics {
	u16     drops_l4s;
	u16     drops_classic;
};

static inline void testbed_metrics_init(struct testbed_metrics *testbed)
{
	testbed->drops_l4s = 0;
	testbed->drops_classic = 0;
}

static inline void __testbed_inc_drop_count(struct testbed_metrics *testbed,
					    bool l4s)
{
	if (l4s)
		testbed->drops_l4s++;
	else
		testbed->drops_classic++;
}

static inline void testbed_inc_drop_count(struct testbed_metrics *testbed,
					  struct sk_buff *skb, bool l4s)
{

	u32 wlen = skb_network_offset(skb);

	switch (tc_skb_protocol(skb)) {
	case htons(ETH_P_IP):
		wlen += sizeof(struct iphdr);
		if (!pskb_may_pull(skb, wlen))
			break;

		__testbed_inc_drop_count(testbed, l4s);
		break;
	case htons(ETH_P_IPV6):
		wlen += sizeof(struct iphdr);
		if (!pskb_may_pull(skb, wlen))
			break;

		__testbed_inc_drop_count(testbed, l4s);
		break;
	}
}

static inline u32 testbed_write_drops(struct testbed_metrics *testbed, bool l4s)
{
	u32 drops, remainder;

	if (l4s) {
		drops = int2fl(testbed->drops_l4s, DROPS_M, DROPS_E,
			       &remainder);
		if (remainder > 10) {
			pr_info("High (>10) drops ecn remainder:  %u\n",
				remainder);
		}
		testbed->drops_l4s = (__force __u16)remainder;
	} else {
		drops = int2fl(testbed->drops_classic, DROPS_M, DROPS_E,
			       &remainder);
		if (remainder > 10) {
			pr_info("High (>10) drops nonecn remainder:  %u\n",
				remainder);
		}
		testbed->drops_classic = (__force __u16)remainder;
	}
	return drops;
}

static inline void testbed_add_metrics_ipv4(struct sk_buff *skb,
					    struct testbed_metrics *testbed,
					    u16 qdelay, bool l4s)
{
	struct iphdr *iph = ip_hdr(skb);
	u16 drops, id;
	u32 check;

	check = ntohs((__force __be16)iph->check) + ntohs(iph->id);
	if ((check + 1) >> 16)
		check = (check + 1) & 0xffff;
	drops = (__force __u16)testbed_write_drops(testbed, l4s);
	/* use upper 5 bits in id field to store number of drops before
	 * the current packet
	 */
	id = qdelay | (drops << 11);

	check -= id;
	check += check >> 16; /* adjust carry */

	iph->id = htons(id);
	iph->check = (__force __sum16)htons(check);
}

/* Add metrics used by traffic analyzer to packet before dispatching.
 * qdelay is the time in units of 1024 ns that the packet spent in the queue.*/
static inline void testbed_add_metrics(struct sk_buff *skb,
				       struct testbed_metrics *testbed,
				       u32 qdelay_us, bool l4s)
{
	int wlen = skb_network_offset(skb);
	u32 qdelay_remainder;
	u16 qdelay;

	/* queue delay is converted from us (1024 ns; >> 10) to units
	 * of 32 us and encoded as float
	 */
	qdelay = (__force __u16)int2fl(qdelay_us >> 5, QDELAY_M, QDELAY_E,
				       &qdelay_remainder);
	if (qdelay_remainder > 20) {
		pr_info("High (>20) queue delay remainder:  %u\n",
			qdelay_remainder);
	}

	/* TODO: IPv6 support using flow label (and increase resolution?) */
	switch (tc_skb_protocol(skb)) {
	case htons(ETH_P_IP):
		wlen += sizeof(struct iphdr);
		if (!pskb_may_pull(skb, wlen) ||
		    skb_try_make_writable(skb, wlen))
			break;

		testbed_add_metrics_ipv4(skb, testbed, qdelay, l4s);
		break;
	default:
		break;
	}
}
