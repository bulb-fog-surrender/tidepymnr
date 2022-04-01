#A stratum compatible miniminer
#based in the documentation
#https://slushpool.com/help/#!/manual/stratum-protocol
#2017-2019 Martin Nadal https://martinnadal.eu

import socket
import json
import random
import tdc_mine
import time
from multiprocessing import Process, Queue, cpu_count


bfh = bytes.fromhex


def hash_decode(x: str) -> bytes:
    return bfh(x)[::-1]


def target_to_bits(target: int) -> int:
    c = ("%066x" % target)[2:]
    while c[:2] == '00' and len(c) > 6:
        c = c[2:]
    bitsN, bitsBase = len(c) // 2, int.from_bytes(bfh(c[:6]), byteorder='big')
    if bitsBase >= 0x800000:
        bitsN += 1
        bitsBase >>= 8
    return bitsN << 24 | bitsBase


def bits_to_target(bits: int) -> int:
    bitsN = (bits >> 24) & 0xff
    if not (0x03 <= bitsN <= 0x20):
        raise Exception("First part of bits should be in [0x03, 0x1d]")
    bitsBase = bits & 0xffffff
    if not (0x8000 <= bitsBase <= 0x7fffff):
        raise Exception("Second part of bits should be in [0x8000, 0x7fffff]")
    return bitsBase << (8 * (bitsN - 3))


def bh2u(x: bytes) -> str:
    """
    str with hex representation of a bytes-like object
    >>> x = bytes((1, 2, 10))
    >>> bh2u(x)
    '01020A'
    """
    return x.hex()


def miner_thread(xblockheader, difficult):
    nonce = random.randint(0, 2 ** 32 - 1)  # job.get('nonce')
    nonce_and_hash = tdc_mine.miner_thread(xblockheader.encode('utf8'), bytes(str(difficult), "utf-8"), nonce)
    z = nonce_and_hash.decode('utf-8').split(',')
    return z


def worker(job, sock, number):
    xnonce = "00000000"
    print(f"worker {number} start")
    xblockheader0 = job.get('xblockheader0')
    job_id = job.get('job_id')
    extranonce2 = job.get('extranonce2')
    ntime = job.get("ntime")
    difficult = job.get('difficult')
    address = job.get('address')
    xblockheader = xblockheader0 + xnonce
    payload1 = '{"params": ["' + address + '", "' + job_id + '", "' + extranonce2 + '", "' + ntime + '", "'
    payload2 = '"], "id": 4, "method": "mining.submit"}\n'
    while 1:
        started = time.time()
        z = miner_thread(xblockheader, difficult)
        print(f'{number} thread yay!!! Time:', time.time() - started, 'Diff', difficult)
        sock.sendall(bytes(payload1 + z[0] + payload2, "UTF-8"))


def miner(address, host, port, cpu_count=cpu_count()):
    print("address:{}".format(address))
    print("host:{} port:{}".format(host, port))
    print("Count threads: {}".format(cpu_count))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    print("Socket connected")

    sock.sendall(b'{"id": 1, "method": "mining.subscribe", "params": ["pytideminer-1.0.0"]}\n')
    lines = sock.recv(1024).decode().split('\n')
    response = json.loads(lines[0])
    sub_details, extranonce1, extranonce2_size = response['result']
    extranonce2 = '00' * extranonce2_size
    sock.sendall(b'{"params": ["' + address.encode() + b'", "password"], "id": 2, "method": "mining.authorize"}\n')
    print("Mining authorize")

    procs = []
    count = cpu_count
    print("start mining")

    try:
        while True:
            response = b''
            comeback = sock.recv(2024)
            print(comeback)
            response += comeback

            # get rid of empty lines
            if b'mining.set_difficulty' in response:
                diff = [json.loads(res) for res in response.decode().split('\n') if
                        len(res.strip()) > 0 and 'mining.set_difficulty' in res]
                difficult = diff[0]['params'][0]
                print("new stratum difficulty: ", difficult)

            if b'mining.notify' in response:
                responses = [json.loads(res) for res in response.decode().split('\n') if
                             len(res.strip()) > 0 and 'mining.notify' in res]

                job_id, prevhash, coinb1, coinb2, merkle_branch, version, nbits, ntime, clean_jobs \
                    = responses[0]['params']
                d = ''

                for h in merkle_branch:
                    d += h

                merkleroot_1 = tdc_mine.sha256d_str(coinb1.encode('utf8'), extranonce1.encode('utf8'),
                                                    extranonce2.encode('utf8'), coinb2.encode('utf8'), d.encode('utf8'))

                xblockheader0 = version + prevhash + merkleroot_1.decode('utf8') + ntime + nbits
                print("Mining notify")

                for proc in procs:
                    proc.terminate()
                    print("worker terminate")
                procs = []
                for number in range(count):
                    proc = Process(target=worker, args=({"xblockheader0": xblockheader0,
                           "job_id": job_id,
                           "extranonce2": extranonce2,
                           "ntime": ntime,
                           "difficult": difficult,
                           'address':address
                           }, sock, number + 1))
                    proc.daemon = True
                    procs.append(proc)
                    proc.start()

    except KeyboardInterrupt:
        for proc in procs:
            proc.terminate()
        sock.close()
    except:
        try:
            for proc in procs:
                proc.terminate()
        except:
            pass
        try:
            sock.close()
        except:
            pass
        miner(address, host, port, cpu_count)


if __name__ == "__main__":
    import argparse
    import sys

    # Parse the command line
    parser = argparse.ArgumentParser(description="PyMiner is a Stratum CPU mining client. "
                                                 "If you like this piece of software, please "
                                                 "consider supporting its future development via "
                                                 "donating to one of the addresses indicated in the "
                                                 "README.md file")

    parser.add_argument('-o', '--url', default="pool.tidecoin.exchange:3032", help='mining server url (eg: pool.tidecoin.exchange:3033)')
    parser.add_argument('-u', '--user', dest='username', default='TSrAZcfyx8EZdzaLjV5ketPwtowgw3WUYw.default', help='username for mining server',
                        metavar="USERNAME")
    parser.add_argument('-t', '--threads', dest='threads', default=cpu_count(), help='count threads',
                        metavar="USERNAME")

    options = parser.parse_args(sys.argv[1:])

    miner(options.username, options.url.split(":")[0], int(options.url.split(":")[1]), int(options.threads))
