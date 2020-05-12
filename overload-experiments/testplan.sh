#!/bin/bash

HERE=$(realpath $(dirname $0))

function _run()
{
    "${HERE}/testrunner.py" -c "${HERE}/results/100M_20ms_classic_protection_$1" -a "dualpi2 classic_protection $1%"
}

_run 0
_run 10
_run 25
