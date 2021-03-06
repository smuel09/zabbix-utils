#!/usr/bin/env python3
import os
import sys
import time
import json
import pickle
import hashlib
import requests
import argparse
import simpleflock
import configparser
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

Config = configparser.ConfigParser()
Config.read(
    os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        'rabbitmq.cfg'
    )
)

try:
    URL = Config.get('Default', 'url')
    USER = Config.get('Default', 'user')
    PASS = Config.get('Default', 'pass')
except Exception:
    print("Can't load config file")
    sys.exit(1)


class Cache(object):
    def __init__(self, ident, ttl=60, verbose=0):
        ident = hashlib.sha1(ident.encode('ascii')).hexdigest()
        self.ttl = ttl
        self.verbose = verbose
        self.fileName = "/tmp/zabbix_rabbitmq.{}.cache".format(ident)
        self.fileLock = "{}.lock".format(self.fileName)

    def is_valid(self):
        if not os.path.exists(self.fileName):
            if self.verbose > 0:
                print("Cache file does not exist {}.".format(self.fileName))
            return False

        statbuf = os.stat(self.fileName)
        if (time.time() - statbuf.st_mtime) > self.ttl:
            if self.verbose > 0:
                print("Cache file expired")
            return False

        return True

    def write(self, payload):
        with open(self.fileName, 'wb') as f:
            if self.verbose > 0:
                print("Writing cache")
            pickle.dump(payload, f)

    def read(self):
        with open(self.fileName, 'rb') as f:
            if self.verbose > 0:
                print("Reading cache.")
            return pickle.load(f)


class API(object):
    def __init__(self, url, user, passwd, verbose=0):
        self.url = url
        self.user = user
        self.passwd = passwd
        self.verbose = verbose
        self.payload = {}

    def getNodeHealth(self, nodeName):
        if self.verbose > 0:
            print("Fetching stats from API")
        r = requests.get(
            "{}/api/healthchecks/node/{}".format(self.url, nodeName),
            auth=(self.user, self.passwd),
            verify=False
        )
        data = r.json()
        return data['status']

    def getHealthcheck(self):
        if self.verbose > 0:
            print("Fetching stats from API")
        r = requests.get(
            "{}/api/healthchecks/node".format(self.url),
            auth=(self.user, self.passwd),
            verify=False
        )
        return r.json()

    def getOverview(self):
        if self.verbose > 0:
            print("Fetching stats from API")
        r = requests.get(
            "{}/api/overview".format(self.url),
            auth=(self.user, self.passwd),
            verify=False
        )
        return r.json()

    def getQueueStats(self):
        if self.verbose > 0:
            print("Fetching stats from API")
        r = requests.get(
            "{}/api/queues".format(self.url),
            auth=(self.user, self.passwd),
            verify=False
        )
        data = {}
        for queue in r.json():
            if not queue['vhost'] in data:
                data[queue['vhost']] = {}
            data[queue['vhost']][queue['name']] = queue
        return data

    def __enter__(self):
        c = Cache(self.url, verbose=self.verbose)
        with simpleflock.SimpleFlock(c.fileLock, timeout=10):
            if c.is_valid():
                self.payload = c.read()
            else:
                self.payload['overview'] = self.getOverview()
                self.payload['queues'] = self.getQueueStats()
                self.payload['healthcheck'] = self.getHealthcheck()
                c.write(self.payload)
        if self.verbose > 1:
            print(json.dumps(self.payload))
        return self

    def __exit__(self, ctx_type, ctx_value, ctx_traceback):
        self.payload = None


def doQueues(args):
    if args.discovery:
        with API(URL, USER, PASS, args.verbose) as a:
            retData = {
                'data': []
            }
            for vhostName in a.payload['queues']:
                for queueName in a.payload['queues'][vhostName]:
                    retData['data'].append({
                        '{#VHOSTNAME}': vhostName,
                        '{#QUEUENAME}': queueName
                    })
            print(json.dumps(retData))
            sys.exit(0)
    elif args.itemKey:
        if not args.vhost or not args.queue:
            print("-v and -q required with -k")
            sys.exit(0)

        with API(URL, USER, PASS, args.verbose) as a:
            try:
                keyPath = args.itemKey.split('.')
                data = a.payload['queues'][args.vhost][args.queue]
                if len(keyPath) == 1:
                    print(data[args.itemKey])
                elif len(keyPath) == 2:
                    print(data[keyPath[0]][keyPath[1]])
                else:
                    print('Unknown')
                    sys.exit(1)
            except KeyError:
                print('Unknown')
                sys.exit(1)
            else:
                sys.exit(0)
    else:
        pQueues.print_help()


def doGeneral(args):
    if args.discovery:
        with API(URL, USER, PASS, args.verbose) as a:
            retData = {
                'data': []
            }
            data = a.payload['overview']['listeners']
            for listener in data:
                if listener['protocol'] == 'clustering':
                    retData['data'].append({
                        '{#NODENAME}': listener['node']
                    })
            print(json.dumps(retData))
            sys.exit(0)
    elif args.itemKey:
        with API(URL, USER, PASS, args.verbose) as a:
            try:
                keyPath = args.itemKey.split('.')
                data = a.payload['overview']
                if len(keyPath) == 1:
                    print(data[args.itemKey])
                elif len(keyPath) == 2:
                    print(data[keyPath[0]][keyPath[1]])
                else:
                    print('Unknown')
                    sys.exit(1)
            except KeyError:
                print('Unknown')
                sys.exit(1)
            else:
                sys.exit(0)
    else:
        pGeneral.print_help()


def doHCheck(args):
    if args.itemKey:
        with API(URL, USER, PASS, args.verbose) as a:
            try:
                data = a.payload['healthcheck']
                print(data[args.itemKey])
            except KeyError:
                print('Unknown')
                sys.exit(1)
            else:
                sys.exit(0)
    elif args.nodeName:
        with API(URL, USER, PASS, args.verbose) as a:
            print(a.getNodeHealth(args.nodeName))
            sys.exit(0)
    else:
        pHCheck.print_help()


parser = argparse.ArgumentParser(description='RabbitMQ Zabbix')
subparsers = parser.add_subparsers(help='sub-command help')

pQueues = subparsers.add_parser('queues',
                                help='Queue related actions')
pQueues.add_argument('-d', dest='discovery', action='count', default=0,
                     help='Queue Discovery')
pQueues.add_argument('-k', dest='itemKey', help='Key to get')
pQueues.add_argument('-v', dest='vhost', help='VHostName')
pQueues.add_argument('-q', dest='queue', help='QueueName')
pQueues.add_argument('--verbose', dest='verbose', action='count', default=0,
                     help='Verbosity')
pQueues.set_defaults(func=doQueues)

pGeneral = subparsers.add_parser('server',
                                 help='General')
pGeneral.add_argument('-d', dest='discovery', action='count', default=0,
                      help='Node Discovery')
pGeneral.add_argument('-k', dest='itemKey', help='Key to get')
# pGeneral.add_argument('-v', dest='vhost', help='VHostName')
# pGeneral.add_argument('-q', dest='queue', help='QueueName')
pGeneral.add_argument('--verbose', dest='verbose', action='count', default=0,
                      help='Verbosity')
pGeneral.set_defaults(func=doGeneral)

pHCheck = subparsers.add_parser('healthcheck',
                                help='Healthcheck')
pHCheck.add_argument('-k', dest='itemKey', help='Healthcheck items')
pHCheck.add_argument('-n', dest='nodeName', help='Node Health')
pHCheck.add_argument('--verbose', dest='verbose', action='count', default=0,
                     help='Verbosity')
pHCheck.set_defaults(func=doHCheck)


if len(sys.argv) == 1:
    parser.print_help()
    sys.exit(0)

args = parser.parse_args()
args.func(args)

sys.exit(2)
