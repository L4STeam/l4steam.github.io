#!/bin/bash
# SPDX-License-Identifier: BSD-3 Clause
# Copyright (C) 2020, Nokia

set -e

HERE=$(realpath $(dirname $0))

if [[ "$EUID" != 0 ]]; then
    echo "Running as un-privileged user, will use \`sudo\` where needed"
    SUDO="sudo"
else
    SUDO=""
fi

DATA_DIR=${DATA_DIR:-.}

# {c*}-[br0]-aqm-[br1]-{s*}
HOST_PAIRS=${HOST_PAIRS:-1}
NETNS=(aqm)
for i in $(seq $HOST_PAIRS); do
     NETNS+=(c$i s$i)
 done
BRIDGES=(br0 br1)

HOSTS_BACK="/etc/hosts.back"
function restore_hosts()
{
    [ -f "HOSTS_BACK" ] && $SUDO mv "$HOSTS_BACK" /etc/hosts || true
}

if [ -f "$HOSTS_BACK" ]; then
    restore_hosts
fi

declare -A ECN
declare -A CCA
declare -A PAIR_DELAY
for i in $(seq $HOST_PAIRS); do
    ECN[s$i]=$(eval echo '${'CC${i}_ECN':-0}')
    ECN[c$i]=$(eval echo '${'CC${i}_ECN':-0}')
    CCA[c$i]=$(eval echo '${'CC${i}_CCA':-prague}')
    CCA[s$i]=$(eval echo '${'CC${i}_CCA':-prague}')
    PAIR_DELAY[$i]=$(eval echo '${'C${i}_DELAY':-0ms}')
done

RATE=${RATE:-100Mbit}
DELAY=${DELAY:-0ms}
AQM=${AQM:-dualpi2}
LOG_PATTERN=${LOG_PATTERN:-}

TIME=${TIME:-10}

BASE_BR0=10.0.1
BASE_BR1=10.0.2

declare -A IPADDR
for i in $(seq $HOST_PAIRS); do
    IPADDR[c${i}-e0]="${BASE_BR0}.${i}"
    IPADDR[s${i}-e0]="${BASE_BR1}.${i}"
done
IPADDR[aqm-e0]="${BASE_BR0}.254"
IPADDR[aqm-e1]="${BASE_BR1}.254"

DELAY_DUMP=${HERE}/qdelay_dump
DELAY_DUMPER="${DELAY_DUMP}/qdelay_dump"

make -C "$DELAY_DUMP"

function macaddr()
{
    printf CA:FE:$(printf "$2" | od -t x1 -A n | awk '{ printf "%s:%s",$1,$2; }'):$(printf "$1" | od -t x1 -A n | awk '{ printf "%s:%s",$1,$2; }')
}

function _sudo()
{
    echo "# $@"
    $SUDO "$@"
}

function ns_exec_silent()
{
    $SUDO ip netns exec "$@"
}

function ns_exec()
{
    local nsname
    nsname="$1"
    shift 1
    echo "[${nsname}] $@"
    $SUDO ip netns exec "$nsname" "$@"
}

function ns_create_link()
{
    local ns=$1
    local name=$2
    local key="${ns}-${name}"
    local ipaddr="${IPADDR[$key]}"
    if [ ! -d "/sys/class/net/$key" ]; then
        _sudo ip link add "$key" type veth peer name "$name"
    fi
    if [ -d "/sys/class/net/$name" ]; then
        _sudo ip link set dev "$name" netns "$ns"
    fi
    ns_exec "$ns" ip link set dev "$name" up
    ns_exec "$ns" ethtool -K "$name" gro off gso off tso off
    ns_exec "$ns" ip link set dev "$name" address "$(macaddr $1 $2)"
    ns_exec "$ns" ip address add dev "$name" "${ipaddr}/24"
    _sudo ip link set dev "$key" up
    _sudo ethtool -K "$key" gro off gso off tso off

    echo "$ipaddr $ns"  | $SUDO tee -a /etc/hosts > /dev/null
}

function bridge_if()
{
    local brname="$1"
    local ifname="$2"
    _sudo ip link set dev "$brname" up
    _sudo ip link set master "$brname" dev "$ifname"
    _sudo ip link set dev "$ifname" up
}

function default_gw()
{
    ns_exec "$1" ip route add default via "${IPADDR[$2]}"
}

function setup_aqm()
{
    ns_exec aqm tc qdisc del dev e1 root &> /dev/null || true
    ns_exec aqm tc qdisc add dev e1 root handle 1: htb default 1 direct_qlen 10000
    ns_exec aqm tc class add dev e1 parent 1: classid 1:1 htb rate "$RATE" ceil "$RATE"
    ns_exec aqm tc qdisc add dev e1 parent 1:1 handle 2: $AQM
    ns_exec aqm tc qdisc del dev e0 root &> /dev/null || true
    ns_exec aqm tc qdisc add dev e0 root handle 1: netem delay "$DELAY"

    for i in $(seq $HOST_PAIRS); do
        _sudo tc qdisc del root dev c$i-e0 &> /dev/null || true
        _sudo tc qdisc add dev c$i-e0 root handle 1: netem delay "${PAIR_DELAY[$i]}" 
    done
}

function setup()
{
    _sudo cp /etc/hosts "$HOSTS_BACK"

    for ns in "${NETNS[@]}"; do
        if [ ! -f "/var/run/netns/${ns}" ]; then
            _sudo ip netns add "$ns"
        fi
        ns_exec "$ns" ip link set dev lo up
        ns_create_link "$ns" e0
	# ns_exec "$ns" tc qdisc replace root dev e0 fq
    done
    ns_create_link aqm e1
    ns_exec aqm sysctl -qw net.ipv4.ip_forward=1

    for br in "${BRIDGES[@]}"; do
        if [ ! -d "/sysclass/net/$br" ]; then
            _sudo ip link add dev "$br" type bridge
        fi
        _sudo ip link set dev "$br" up
    done

    bridge_if br0 aqm-e0
    bridge_if br1 aqm-e1
    for i in $(seq $HOST_PAIRS); do
        bridge_if br0 c${i}-e0
        bridge_if br1 s${i}-e0
        default_gw c${i} aqm-e0
        default_gw s${i} aqm-e1
    done
    setup_aqm
}

function set_sysctl()
{
    ns_exec "$1" sysctl -qw "net.ipv4.tcp_congestion_control=${CCA[$1]}"
    ns_exec "$1" sysctl -qw "net.ipv4.tcp_ecn=${ECN[$1]}"
}

function gen_suffix()
{
    if [ -z "$LOG_PATTERN" ]; then
        printf "$1_${CCA[$1]}_${ECN[$1]}_${RATE}_${DELAY}_$(echo $AQM | tr ' /' '_')"
    else
        printf "$1_${LOG_PATTERN}"
    fi
}

function iperf_server()
{
    local ns=$1
    local suffix=$2
    shift 2
    FILTER="ip and src net ${BASE_BR0}.0/24"
    echo "[$ns] iperf3 -s -1 -i .1 -J $@ &> ${DATA_DIR}/iperf_$(gen_suffix $ns)${suffix}.json"
    ns_exec_silent "$ns" iperf3 -1 -s -i .1 -J "$@" \
        &> "${DATA_DIR}/iperf_$(gen_suffix $ns)${suffix}.json" &
    echo "[$ns] "$DELAY_DUMPER e0 $FILTER > "${DATA_DIR}/qdelay_$(gen_suffix $ns).qdelay"
    ns_exec_silent "$ns" "$DELAY_DUMPER" "e0" "$FILTER" \
        > "${DATA_DIR}/qdelay_$(gen_suffix $ns).qdelay" &
}

function iperf_client()
{
    local ns=$1
    local dst=$2
    local suffix=$3
    shift 3
    echo "[$ns] iperf3 -c $dst -i .1 -t $TIME -J $@ &> ${DATA_DIR}/iperf_$(gen_suffix $ns)${suffix}.json"
    ns_exec_silent "$ns" iperf3 -c "$dst" -i .1 -t "$TIME" -J "$@" \
        &> "${DATA_DIR}/iperf_$(gen_suffix $ns)${suffix}.json"
}

function update_network()
{
    ns_exec aqm tc qdisc change dev e0 root handle 1: netem delay "$DELAY"
    for i in $(seq $HOST_PAIRS); do
        _sudo tc qdisc change dev c$i-e0 root handle 1: netem delay "${PAIR_DELAY[$i]}" 
    done
}

function run_test()
{
    setup_aqm

    _sudo killall iperf &> /dev/null || true
    for i in $(seq $HOST_PAIRS); do
        set_sysctl s$i
        set_sysctl c$i
        iperf_server s$i ""
    done
    sleep .1

    echo "Running tests for ${TIME}sec"
    for i in $(seq $HOST_PAIRS); do
        iperf_client c$i s$i "" &
        pid_iperf=$!
    done
    sleep $((TIME+5))
    wait $pid_iperf
    $SUDO killall -SIGHUP $(basename "$DELAY_DUMPER")
    sleep .1
    sync
}

function clean()
{
    for ns in "${NETNS[@]}"; do
        if [ ! -f "/var/run/netns/${ns}" ]; then
            continue
        fi
        _sudo ip link del dev "${ns}-e0" &> /dev/null || true
        _sudo ip link del dev "${ns}-e1" &> /dev/null || true
        _sudo ip netns pids "$ns" | xargs '-I{}' $SUDO kill '{}' &> /dev/null || true
        sleep 0.1
        _sudo ip netns pids "$ns" | xargs '-I{}' $SUDO kill -s9 '{}' &> /dev/null || true
	    _sudo ip netns del "$ns"
    done
    for br in "${BRIDGES[@]}"; do
        if [ ! -d "/sys/class/net/$br" ]; then
            continue
        fi
        _sudo ip link set dev "$br" down || true
        _sudo ip link del dev "$br" || true
    done
    restore_hosts
}

trap clean SIGINT

function usage()
{
    echo "Usage: $THIS [-chpsvt]"
    echo "       -c   clean"
    echo "       -d   debug script execution"
    echo "       -h   show this message"
    echo "       -s   setup the network" 
    echo "       -u   update the network" 
    echo "       -t   run a test"
    echo ""
    echo "  Congestion control algorithms/ecn settings of nodes are controlled "
    echo "  through the following env variables:"
    echo "      HOST_PAIRS [$HOST_PAIRS] -- The number of host pairs"
    for i in $(seq $HOST_PAIRS); do
    echo "      CC${i}_CCA [${CCA[c$i]}] -- The net.ipv4.tcp_congestion_control sysctl for the c$i-s$i pairs"
    echo "      CC${i}_ECN [${ECN[c$i]}] -- The net.ipv4.tcp_ecn sysctl for the c$i-s$i pair "
    done
    echo ""
    echo "  Bottleneck link characteristics are controlled through the following env variables:"
    echo "      RATE [$RATE] -- The bottleneck bandwidth"
    echo "      DELAY [$DELAY] -- The base RTT"
    echo "      AQM [$AQM] -- The AQM parameters"
    echo ""
    echo "  Additional delay can be set for each sender-receiver pair:"
    for i in $(seq $HOST_PAIRS); do
    echo "      CC${i}_DELAY [${PAIR_DELAY[$i]}] -- The additional delay for the c$i-s$i pair"
    done
    echo ""
    echo "  Each transfert will run for TIME[$TIME] seconds."
    echo ""
    echo "  You can control the way the data is generated using:"
    echo "      DATA_DIR [$DATA_DIR] -- The directory where data should be stored"
    echo "      LOG_PATTERN [$LOG_PATTERN] -- The pattern to identify experiment data, instead of e.g., for c1, $(gen_suffix c1)"
}

DBG_FLAG=""
if [[ $# > 0 ]]; then
    while getopts "dchstu" o; do
        case "${o}" in
            c)
                clean
                ;;
            d)
                set -x
                ;;
            h)
                usage
                ;;
            s)
                setup
                ;;
            u)
                update_network
                ;;
            t)
                run_test
                ;;
            *)
                usage
                ;;
        esac
    done
else
    usage
fi
