#!/usr/bin/env python3

import socket
import threading
import queue
import select
import time
import uuid
import json

import P12common

server_ip = '127.0.0.1'
server_port = 4588
reconnect_timeout = 10
select_timeout = 1
my_uuid = str(uuid.uuid4())

msgq = queue.Queue()


def serve_msg(s, msg):
    # serve message from server
    obj = json.loads(msg.decode('utf-8'))
    if 'register' in obj.keys():
        if obj['register'] == 'ok':
            print("successfully registered on server")
            # request task
            msgq.put({"request": "task"})
        else:
            print("Failed to register on server: %s" % obj['register'])
    if 'task' in obj.keys():
        # can take task?
        task = obj['task']
        # try to take task
        obj_to_srv = {'state': {task: 'started'}}
        msgq.put(obj_to_srv)
    return True


while True:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print("Try to connect")
    connect_result = s.connect_ex((server_ip, server_port))
    if connect_result == 0:
        # register on server as soon as possible
        msgq.put({'register': my_uuid})
        # have connected to server
        print("connected")
        while True:
            rd, wr, exc = select.select([s],
                                        [] if msgq.empty() else [s],
                                        [s],
                                        select_timeout)
            if rd:
                # have something to read
                print("reading")
                msg_len_s = s.recv(4)
                if len(msg_len_s) == 0:
                    # closed connection
                    print("server close connection")
                    s.close()
                    break
                msg_len = int.from_bytes(msg_len_s, 'little')
                msg = s.recv(msg_len)
                print("received %s" % msg)
                serve_msg(s, msg)
            if wr:
                print("writing")
                # can send
                if not msgq.empty():
                    if P12common.send_msg(s, json.dumps(msgq.get())):
                        print("sent to server")
                    else:
                        # some error
                        print("ERR while sending")
            if exc:
                # some exception
                print("something wrong")
                s.close()
                break
            print("waiting...")
        time.sleep(3)
    else:
        print("connect error: %d" % connect_result)
        # retry connect after pause
        time.sleep(reconnect_timeout)

    s.close()
    while not msgq.empty():
        msgq.get()
