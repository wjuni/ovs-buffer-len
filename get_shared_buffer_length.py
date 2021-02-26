#!/usr/bin/env python

import sys
import socket
import json
import time
import timeit
import re
import pandas as pd
import argparse
from collections import defaultdict

sock = None

def obtain_ovs_pid():
    with open("/var/run/openvswitch/ops-switchd.pid", "r") as f:
        return int(f.read().strip())

def build_query(query):
    req = {"id": build_query.qid, "method": "plugin/debug", "params": ["drivsh", query + "\n"]}
    build_query.qid += 1
    return json.dumps(req)
build_query.qid = 0

def ovs_query(query_str):
    query = build_query(query_str)
    sock.send(query.encode('utf-8'))
    response = ''
    while True:
        response += sock.recv(1000000).decode('utf-8')
        try:
            resp_obj = json.loads(response)
            return resp_obj['result']
        except:
            pass
    return None

regex = re.compile(r'XPE(?P<xpe>[0-9])_PIPE(?P<pipe>[0-9]).*\[(?P<idx>[0-9]+)\]: .*<(.*,)*SHARED_COUNT=(?P<cnt>[0-9a-fA-Fx]+),(.*)>')
def parse_shared_count(raw_str):
    d = defaultdict(int)
    for line in raw_str.split('\n'):
        match = regex.search(line)
        if match is None:
            continue
        cnt = match.group('cnt')
        xpe = match.group('xpe')
        pipe = match.group('pipe')
        idx = match.group('idx')
        d["xpe{}_pipe{}_{}".format(xpe, pipe, idx)] += int(cnt, 16) if '0x' in cnt else int(cnt)

    return d

def get_shared_count(xpe, pipe, idx=None):
    query_str = "d MMU_WRED_PORT_SP_SHARED_COUNT_XPE{}_PIPE{} {} raw SHARED_COUNT".format(xpe, pipe, idx if idx is None else str(idx) + ' 1 ')
    response = ovs_query(query_str)
    return parse_shared_count(response) 

def scan():
    reported = set()
    try:
        print("Collecting stats! Generate some traffic!")
        while True:
            result = {}
            result.update(get_shared_count(0, 0))
            result.update(get_shared_count(0, 1))
            result.update(get_shared_count(1, 2))
            result.update(get_shared_count(1, 3))
            result.update(get_shared_count(2, 0))
            result.update(get_shared_count(2, 1))
            result.update(get_shared_count(3, 2))
            result.update(get_shared_count(3, 3))
            for key, cell_cnt in result.items():
                if cell_cnt > 10 and key not in reported:
                    reported.add(key)
                    print("{} : Using {} cells".format(key, cell_cnt))
    except KeyboardInterrupt:
        pass

def benchmark():
    total = []
    time_offset = time.time()
    idx = 0
    try:
        print("Collecting stats until KeyboardInterrupt...")
        for i in range(1000000):
            result = {}
            result.update(get_shared_count(args.xpe, args.pipe, args.index))
            if len(result) == 0:
                continue
            result['time_ms'] = (time.time() - time_offset) * 1000
            total.append(result)
            idx += 1
    except KeyboardInterrupt:
        print("Collected %d data points, processing..." % idx)
        pass

    df = pd.DataFrame(total)
    df = df.set_index('time_ms')
    df.to_excel("switch_buffer_len.xlsx", sheet_name="raw")
    print(df)

args = None
def main():
    global sock, args
    parser = argparse.ArgumentParser()
    parser.add_argument('--xpe', type=int, help='XPE #')
    parser.add_argument('--pipe', type=int, help='PIPE #')
    parser.add_argument('--index', type=int, help='Entry Index')
    parser.add_argument('--scan', action='store_true', default=False)
    args = parser.parse_args()
    if not args.scan and (args.xpe is None or args.pipe is None):
        print("XPE and PIPE is required for benchmark mode!", file=sys.stderr)
        parser.print_help()
        return 1

    ovs_pid = obtain_ovs_pid()
    if ovs_pid is None:
        return 1

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect("/var/run/openvswitch/ops-switchd.%d.ctl" % ovs_pid)

    if scan:
        scan()
    else:
        elapsed = timeit.timeit(benchmark, number=1)
        print("Took %g seconds" % elapsed)

    sock.close()

    return 0


if __name__=="__main__":
    ret_code = main()
    sys.exit(ret_code)
   
