#!/bin/bash
# SPDX-License-Identifier: BSD-3 Clause
# Copyright (C) 2020, Nokia

set -e

if [[ "$EUID" != 0 ]]; then
    echo "Running as un-privileged user, will use \`sudo\` where needed"
    SUDO="sudo"
else
    SUDO=""
fi

DATA_DIR=${DATA_DIR:-.}

# {c1,c2}-[br0]-aqm-[br1]-{s1,s2}
NETNS=(c1 c2 s1 s2 aqm)
BRIDGES=(br0 br1)

HOSTS_BACK="/etc/hosts.back"
function restore_hosts()
{
    [ -f "HOSTS_BACK" ] && $SUDO mv "$HOSTS_BACK" /etc/hosts || true
}

if [ -f "$HOSTS_BACK" ]; then
    restore_hosts
fi

C1_CCA=${C1_CCA:-prague}
C1_ECN=${C1_ECN:-2}
C2_CCA=${C2_CCA:-cubic}
C2_ECN=${C2_ECN:-2}

declare -A ECN
ECN[c1]=$C1_ECN
ECN[s1]=$C1_ECN
ECN[c2]=$C2_ECN
ECN[s2]=$C2_ECN

declare -A CCA
CCA[c1]=$C1_CCA
CCA[s1]=$C1_CCA
CCA[c2]=$C2_CCA
CCA[s2]=$C2_CCA

RATE=${RATE:-100Mbit}
DELAY=${DELAY:-0ms}
AQM=${AQM:-dualpi2}
LOG_PATTERN=${LOG_PATTERN:-}
CC1_DELAY=${CC1_DELAY:-0ms}
CC2_DELAY=${CC2_DELAY:-0ms}

TIME=${TIME:-10}

BASE_BR0=10.0.1
BASE_BR1=10.0.2

declare -A IPADDR
IPADDR[c1-e0]="${BASE_BR0}.1"
IPADDR[c2-e0]="${BASE_BR0}.2"
IPADDR[aqm-e0]="${BASE_BR0}.3"
IPADDR[s1-e0]="${BASE_BR1}.1"
IPADDR[s2-e0]="${BASE_BR1}.2"
IPADDR[aqm-e1]="${BASE_BR1}.3"

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
    _sudo ip link set dev "$brname" up
    shift 1
    for ifname in "$@"; do
        _sudo ip link set master "$brname" dev "$ifname"
        _sudo ip link set dev "$ifname" up
    done
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

    _sudo tc qdisc del root dev c1-e0 &> /dev/null || true
    _sudo tc qdisc del root dev c2-e0 &> /dev/null || true
    _sudo tc qdisc add dev c1-e0 root handle 1: netem delay "$CC1_DELAY" 
    _sudo tc qdisc add dev c2-e0 root handle 1: netem delay "$CC2_DELAY"
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
	ns_exec "$ns" tc qdisc replace root dev e0 fq
    done
    ns_create_link aqm e1
    ns_exec aqm sysctl -qw net.ipv4.ip_forward=1

    for br in "${BRIDGES[@]}"; do
        if [ ! -d "/sysclass/net/$br" ]; then
            _sudo ip link add dev "$br" type bridge
        fi
        _sudo ip link set dev "$br" up
    done

    bridge_if br0 c1-e0 c2-e0 aqm-e0
    default_gw c1 aqm-e0
    default_gw c2 aqm-e0
    bridge_if br1 s1-e0 s2-e0 aqm-e1
    default_gw s1 aqm-e1
    default_gw s2 aqm-e1
    setup_aqm
}

function set_sysctl()
{
    for n in "$@"; do
        ns_exec "$n" sysctl -qw "net.ipv4.tcp_congestion_control=${CCA[$n]}"
        ns_exec "$n" sysctl -qw "net.ipv4.tcp_ecn=${ECN[$n]}"
    done
}

function gen_suffix()
{
    if [ -z "$LOG_PATTERN" ]; then
        printf "$1_${CCA[$1]}_${ECN[$1]}_${RATE}_${DELAY}_$(echo $AQM | tr ' /' '_')"
    else
        printf "$1_${LOG_PATTERN}"
    fi
}

function iperf_servers()
{
    _sudo killall iperf &> /dev/null || true
    for i in "$@"; do
        ns_exec "$i" iperf3 -s -i .1 \
            &> "${DATA_DIR}/iperf_$(gen_suffix $i).log" &
    done
    sleep .1
}

function iperf_client()
{
    ns_exec_silent "$1" iperf3 -c "$2" -i .1 -t "$TIME" -J \
        &> "${DATA_DIR}/iperf_$(gen_suffix $1).json"
}

function update_network()
{
    ns_exec aqm tc qdisc change dev e0 root handle 1: netem delay "$DELAY"
    _sudo tc qdisc change dev c1-e0 root handle 1: netem delay "$CC1_DELAY"
    _sudo tc qdisc change dev c2-e0 root handle 1: netem delay "$CC2_DELAY"
}

function run_test()
{
    setup_aqm

    set_sysctl s1 s2 c1 c2

    iperf_servers s1 s2

    echo "Running tests for ${TIME}sec"
    # Block on the second client before gathering results
    iperf_client c1 s1 &
    pid_1=$!
    iperf_client c2 s2 &
    pid_2=$!
    wait $pid_2
    wait $pid_1
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
    echo "      C1_CCA [$C1_CCA] -- The net.ipv4.tcp_congestion_control sysctl for the c1-s1 pair"
    echo "      C2_CCA [$C2_CCA] -- The net.ipv4.tcp_congestion_control sysctl for the c2-s2 pair"
    echo "      C1_ECN [$C1_ECN] -- The net.ipv4.tcp_ecn sysctl for the c1-s1 pair"
    echo "      C2_ECN [$C2_ECN] -- The net.ipv4.tcp_ecn sysctl for the c2-s2 pair"
    echo ""
    echo "  Bottleneck link characteristics are controlled through the following env variables:"
    echo "      RATE [$RATE] -- The bottleneck bandwidth"
    echo "      DELAY [$DELAY] -- The base RTT"
    echo "      AQM [$AQM] -- The AQM parameters"
    echo ""
    echo "  Additional delay can be set for each sender-receiver pair:"
    echo "      CC1_DELAY [$CC1_DELAY] -- The additional delay for the c1-s1 pair"
    echo "      CC2_DELAY [$CC2_DELAY] -- The additional delay for the c2-s2 pair"
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
