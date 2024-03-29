#!/usr/bin/env python3

import socket
import threading
import queue
import select
import time
import uuid
import json
import copy
import logging
import sys

import P12common

server_ip = '127.0.0.1'
if len(sys.argv) > 1:
    server_ip = sys.argv[1]
server_port = 4588
reconnect_timeout = 10
select_timeout = 1
my_uuid = str(uuid.uuid4())

msgq = queue.Queue()

task_thread = threading.Thread()

time_prev = 0
time_delta = 60

registered = False
max_level = {'level': 10, 'matrix': []}

logging.basicConfig(level=logging.DEBUG)


def start_p(matrix, f):
    pairs = [2] * (P12common.F_COUNT + 1)
    pairs[0] = 0
    for m in matrix:
        if f in m:
            for x in m:
                if x != f:
                    pairs[x] = pairs[x] - 1
    return pairs


def check_loops(matrix, index, f, pairs):
    ''' check loops in all facets '''
    if len(matrix[index]) < 2:
        return True
    a = matrix[index][0]
    b = matrix[index][1]
    count = 0
    if pairs[a] == 1:
        count += 1
        if not P12common.test_loop_in_facet(matrix, index, a, f):
            return False
    if pairs[b] == 1:
        count += 1
        if not P12common.test_loop_in_facet(matrix, index, b, f):
            return False
    if count > 1:
        if not P12common.test_loop_in_facet(matrix, index, f, f):
            return False
    return True


def try_last_f(matrix):
    ''' do last facet '''
    pairs = start_p(matrix, P12common.F_COUNT)
    for i_m in range(len(matrix)):
        if len(matrix[i_m]) == 2:
            # test pairs
            for f0 in matrix[i_m]:
                if pairs[f0] < 1:
                    logging.debug("exit by pairs %s" % str(matrix))
                    msgq.put({'stats': {'reason': 'pairs',
                                        'matrix': matrix}})
                    return False
            # test loop
            if not check_loops(matrix, i_m, P12common.F_COUNT, pairs):
                logging.debug("exit by loop %s" % str(matrix))
                msgq.put({'stats': {'reason': 'loop',
                                    'matrix': matrix}})
                return False
            # set
            matrix[i_m].append(P12common.F_COUNT)
            for f0 in matrix[i_m]:
                pairs[f0] -= 1
    # else its solution
    logging.debug("solution %s" % str(matrix))
    msgq.put({'solution': new_m})


def try_next(matrix, f, v_left, ind, pairs, level):
    '''
    matrix - матрица текущая
    f - номер грани
    v_left - оставшееся количество вершин в данной грани
    ind - индекс массива M для проверки
    pairs - массив оставшихся возможных пересечений с другими гранями
    '''
    global time_prev
    if time.time() > time_prev + time_delta:
        time_prev = time.time()
        logging.debug("%s, %s" % (threading.current_thread().name,
                                  str(matrix)))
    my_ind = ind
    prev_m = [0]

    if level > max_level['level']:
        max_level['level'] = level
        max_level['matrix'] = copy.deepcopy(matrix)

    while my_ind + v_left <= P12common.V_COUNT:
        if len(matrix[my_ind]) < 3:
            dupple = 0
            for pf in matrix[my_ind]:
                if pairs[pf] < 1:
                    break
                elif pairs[pf] == 1:
                    dupple = dupple + 1
                    if dupple > 1:
                        break
            else:
                if prev_m != matrix[my_ind] and \
                   check_loops(matrix, ind, f, pairs):
                    prev_m = matrix[my_ind]
                    new_m = copy.deepcopy(matrix)
                    new_m[my_ind].append(f)
                    new_pairs = pairs.copy()
                    for pf in matrix[my_ind]:
                        new_pairs[pf] = new_pairs[pf] - 1
                    if v_left > 1:
                        # продолжаем жарить ту же грань
                        if try_next(new_m, f, v_left - 1,
                                    my_ind + 1, new_pairs,
                                    level + 1):
                            return True
                    else:
                        # переход на следующую грань
                        if f >= P12common.F_COUNT:
                            # граней больше нет => это решение
                            logging.info("Solution found: %s" % str(new_m))
                            msgq.put({'solution': new_m})
                            return True
                        # проверим паросочетания f со всеми предыдущими
                        passed = False
                        for i in range(1, f):
                            if new_pairs[i] > 0:
                                passed = True
                                break
                        if not passed:
                            # жарим следующую грань
                            if f + 1 == P12common.F_COUNT:
                                return try_last_f(new_m)
                            if try_next(new_m, f + 1,
                                        P12common.FV_COUNT - 2,
                                        P12common.FV_COUNT,
                                        start_p(new_m, f + 1),
                                        level + 1):
                                return True
        my_ind = my_ind + 1
    else:
        if level == 1:
            msgq.put({
                'state': {
                    threading.current_thread().name: 'solved'
                         },
                'stats': {
                    'maxlevel': max_level['level'],
                    'matrix': max_level['matrix']
                         }
                     })
            logging.debug("max level: %d, matrix: %s" % (
                           max_level['level'],
                           str(max_level['matrix'])))
        return False


def start_task(task):
    ''' start task if possible '''
    global task_thread
    global max_level
    max_level = {'level': 10, 'matrix': []}
    if not task_thread.is_alive() and task_thread.name == 'waiting':
        logging.info("starting thread to solve task %s" % task)
        matrix = P12common.s_to_m(bytes(task, 'utf-8'))
        task_thread = threading.Thread(target=try_next, args=(
                                       matrix,  # matrix
                                       8,       # f
                                       P12common.FV_COUNT - 2,
                                       P12common.FV_COUNT,
                                       start_p(matrix, 8),
                                       1))
        task_thread.setName(task)
        task_thread.start()
        return True
    # there is not any empty thread
    return False


def serve_msg(s, msg):
    global registered
    # serve message from server
    obj = json.loads(msg.decode('utf-8'))
    if 'register' in obj.keys():
        if obj['register'] == 'ok':
            logging.info("Successfully registered on server")
            registered = True
        else:
            logging.error("Failed to register on server: %s" % obj['register'])
    if 'task' in obj.keys():
        # can take task?
        task = obj['task']
        # try to take task
        if start_task(task):
            msgq.put({'state': {task: 'started'}})
        else:
            msgq.put({'state': {task: 'failed'}})
    return True


connect_result_old = 0
while True:
    registered = False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    logging.info("Try to connect to server %s:%d" % (server_ip, server_port))
    connect_result = s.connect_ex((server_ip, server_port))
    if connect_result == 0:
        connect_result_old = 0
        # register on server as soon as possible
        msgq.put({'register': my_uuid})
        # have connected to server
        logging.info("Successfully connected")
        while True:
            rd, wr, exc = select.select([s],
                                        [] if msgq.empty() else [s],
                                        [s],
                                        select_timeout)
            if rd:
                # have something to read
                msg_len_s = s.recv(4)
                if len(msg_len_s) == 0:
                    # closed connection
                    logging.warn("Server closed connection")
                    s.close()
                    break
                msg_len = int.from_bytes(msg_len_s, 'little')
                msg = s.recv(msg_len)
                logging.debug("Received %s" % msg)
                serve_msg(s, msg)
            if wr:
                # can send
                if not msgq.empty():
                    if not P12common.send_msg(s, json.dumps(msgq.get())):
                        # some error
                        logging.error("ERR while sending msg to server")
            if exc:
                # some exception
                logging.error("Something wrong")
                s.close()
                break

            # check thread
            if registered:
                if (not task_thread.is_alive() and
                   task_thread.name != 'waiting'):
                    logging.info("request new task for thread '%s'" %
                                 task_thread.name)
                    msgq.put({'request': 'task'})
                    task_thread.setName('waiting')

        time.sleep(3)
    else:
        if connect_result != connect_result_old:
            logging.error("Connection error: %d" % connect_result)
            connect_result_old = connect_result
        # retry connect after pause
        time.sleep(reconnect_timeout)

    s.close()

while not msgq.empty():
    msgq.get()
