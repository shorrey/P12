#!/usr/bin/env python3

import socket
import threading
import queue
import select
import json
import time
import copy
import logging

import P12common

listen_ip = '0.0.0.0'
listen_port = 4588
listen_max_conn = 5

free_task_count = 3

free_tasks_file = 'free_tasks.json'
taken_tasks_file = 'taken_tasks.json'
solved_tasks_file = 'solved.txt'  # only append to it
solution_file = 'solution.txt'  # append only!

free_tasks = []  # free task list
taken_tasks = {}  # tasks taken by clients task: {uuid, time, state}
no_more_task = False  # where all tasks was found
task_last_found = b''

logging.basicConfig(level="INFO")

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.setblocking(0)
server.bind((listen_ip, listen_port))
server.listen(listen_max_conn)

inputs = [server]
outputs = []
msgq = {}
uuids = {}

th = None


def remove_sock(s):
    if s in uuids.keys():
        logging.info("Client %s disconnected" % uuids.pop(s))
    if s in outputs:
        outputs.remove(s)
    if s in inputs:
        inputs.remove(s)
    s.close()
    del msgq[s]


def find_next_task(prev_task):
    ''' search for new task
        prev_task - bytes!!! '''
    prev_pos = [0, 0, 0, 0, 0, 4, 5, 6]
    pairs = [  # сколько пар осталось заполнить
        [0, 0, 2, 2, 2],  # 5
        [0, 0, 2, 2, 2, 2],  # 6
        [0, 0, 2, 2, 2, 2, 2]  # 7
    ]
    v = []
    matrix = copy.deepcopy(P12common.STARTM)
    for i in range(len(prev_task)):
        f = i // 9 + 5
        pos = prev_pos[f] + prev_task[i] - 0x60
        v.append(pos)
        prev_pos[f] = pos
        for f0 in matrix[pos]:
            pairs[f - 5][f0] -= 1
        matrix[pos].append(f)
    # now have v (positions) and matrix
    start_v = 0
    start_pos = 11
    if len(v) != 0:
        # not initial calc
        start_v = len(v) - 1
        start_pos = v.pop() + 1
        matrix[start_pos - 1].remove(start_v // 9 + 5)
        for f0 in matrix[start_pos - 1]:
            pairs[start_v // 9][f0] += 1

    while start_v < 9 * 3:
        # print("start_v %d start_pos %d\n%s" %
        #      (start_v, start_pos, str(v)))
        # пробуем поставить v в каждую позицию, начиная со start_pos
        if start_pos >= P12common.V_COUNT:
            # спускаемся на уровень ниже
            start_v = len(v) - 1
            if start_v < 0:
                return None
            start_pos = v.pop() + 1
            matrix[start_pos - 1].remove(start_v // 9 + 5)
            for f0 in matrix[start_pos - 1]:
                pairs[start_v // 9][f0] += 1
            continue

        # check count
        if len(matrix[start_pos]) > 2:
            start_pos += 1
            continue
        # chec same
        if matrix[start_pos] == matrix[start_pos - 1]:
            start_pos += 1
            continue
        # check pairs
        passed = False
        for f0 in matrix[start_pos]:
            passed |= (pairs[start_v // 9][f0] < 1)
        if passed:
            start_pos += 1
            continue
        # check loop
        if not P12common.test_loop_bfs(matrix, start_pos, start_v // 9 + 5):
            start_pos += 1
            continue

        # а теперь ставим и продолжаем
        v.append(start_pos)
        for f0 in matrix[start_pos]:
            pairs[start_v // 9][f0] -= 1
        matrix[start_pos].append(start_v // 9 + 5)
        start_v += 1
        if start_v // 9 > (start_v - 1) // 9:
            start_pos = 11
        else:
            start_pos += 1

    # v - new task
    # print(matrix)
    return P12common.m_to_s(matrix)


def add_tasks():
    global task_last_found
    global no_more_task
    while len(free_tasks) < free_task_count and not no_more_task:
        task = find_next_task(task_last_found)
        if not task:
            no_more_task = True
            return
        task_last_found = task
        free_tasks.append(task.decode('utf-8'))
        try:
            with open(free_tasks_file, "w") as ftf:
                json.dump(free_tasks, ftf)
        except Exception as e:
            logging.error("Write to free tasks file: %s" % str(e))
        logging.info("add task %s to free list" % task.decode('utf-8'))


def take_task(task, client):
    ''' move task from free to taken '''
    if task not in free_tasks:
        return False
    try:
        taken_tasks[task] = {'uuid': uuids[client],
                             'time': time.time(),
                             'state': None}
        msgq[client].put(json.dumps({'task': task}))
    except Exception as e:
        logging.error("Error while marking task: %s" % str(e))
        return False
    free_tasks.remove(task)
    # write to files
    try:
        with open(free_tasks_file, "w") as ftf:
            json.dump(free_tasks, ftf)
    except Exception as e:
        logging.error("Write to free tasks file: %s" % str(e))

    try:
        with open(taken_tasks_file, "w") as ttf:
            json.dump(taken_tasks, ttf)
    except Exception as e:
        logging.error("Write to taken tasks file: %s" % str(e))

    # start add_tasks in other thread
    th = threading.Thread(target=add_tasks, args=())
    th.start()

    return True


def task_state_changed(task, new_state, client):
    ''' Change state of task '''
    if task not in taken_tasks.keys():
        logging.warn("task not in taken task list! (%s)" % task)
        return False
    if taken_tasks[task]['uuid'] != client:
        logging.warn("Client %s changes state of task %s, but its uuid is %s" %
              (client, str(task), taken_tasks[task]['uuid']))

    if new_state == 'started':
        taken_tasks[task]['state'] = 'started'
        taken_tasks[task]['time'] = time.time()

    if new_state == 'solved':
        try:
            with open(solved_tasks_file, "a") as sf:
                print(task, file=sf)
        except Exception as e:
            logging.error("Can not write solved tasks file: %s" % str(e))
        taken_tasks.pop(task)

    elif new_state in ('canceled', 'failed'):
        # client cancel to solve task. return it to free list
        free_tasks.append(task)
        taken_tasks.pop(task)

        try:
            with open(free_tasks_file, "w") as ftf:
                json.dump(free_tasks, ftf)
        except Exception as e:
            logging.error("Write to free tasks file: %s" % str(e))

    try:
        with open(taken_tasks_file, "w") as ttf:
            json.dump(taken_tasks, ttf)
    except Exception as e:
        logging.error("Write to taken tasks file: %s" % str(e))

    return True


def serve_msg(s, msg):
    ''' doing meaage from client '''
    obj = json.loads(msg.decode('utf-8'))
    # print(obj)
    if 'register' in obj.keys():
        # register uuid of client
        for k in uuids.keys():
            if uuids[k] == obj['register']:
                logging.info("Client %s was registered. Re-register" %
                      obj['register'])
                uuids.pop(k)
        uuids[s] = obj['register']
        msgq[s].put(json.dumps({'register': 'ok'}))
        logging.info("Client uuid %s registered" % obj['register'])

    if 'request' in obj.keys():
        if 'task' == obj['request']:
            # client requests task
            if s in uuids:
                logging.info("Client %s request task" % uuids[s])
                if len(free_tasks) > 0:
                    take_task(free_tasks[0], s)
            else:
                logging.warn("Unregistered client request task")
                return False

    if 'state' in obj.keys():
        for task in obj['state'].keys():
            # but must by only one
            logging.info("State of task %s changed to %s" %
                  (task, obj['state'][task]))
            task_state_changed(task, obj['state'][task], uuids[s])

    if 'solution' in obj.keys():
        logging.info("Client %s find solution: %s" % (uuids[s], str(obj['solution'])))
        try:
            with open(solution_file, "a") as f:
                print(obj['solution'], file=f)
        except Exception as e:
            logging.error("error while write to solution file: %s" % str(e))

    if not msgq[s].empty():
        # add socket to output if there is something to send
        if s not in outputs:
            outputs.append(s)
    return True


try:
    with open(free_tasks_file, "r") as ftf:
        free_tasks = json.load(ftf)
except Exception as e:
    logging.warn("Opening free tasks file: %s" % str(e))

try:
    with open(taken_tasks_file, "r") as ttf:
        taken_tasks = json.load(ttf)
except Exception as e:
    logging.warn("Opening taken tasks file: %s" % str(e))

for t in free_tasks + list(taken_tasks.keys()):
    if task_last_found < bytes(t, 'utf-8'):
        task_last_found = bytes(t, 'utf-8')


if len(free_tasks) < free_task_count:
    # need to create tasks
    add_tasks()

try:
    while inputs:
        rd, wr, exc = select.select(inputs, outputs, inputs)
        for s in rd:
            if s is server:
                # new incoming connection
                connection, client_address = s.accept()
                logging.info("Client connected: %s" % str(client_address))
                connection.setblocking(0)
                inputs.append(connection)
                msgq[connection] = queue.Queue()
            else:
                # data from connected client
                try:
                    data = s.recv(4)
                except Exception:
                    remove_sock(s)
                    continue
                if data:
                    try:
                        msg = s.recv(int.from_bytes(data, 'little'))
                        # print(msg)
                    except Exception:
                        # error while reading from socket
                        remove_sock(s)
                    else:
                        serve_msg(s, msg)
                else:
                    # client closed connection
                    remove_sock(s)
        for s in wr:
            try:
                next_msg = msgq[s].get_nowait()
            except queue.Empty:
                outputs.remove(s)
            else:
                P12common.send_msg(s, next_msg)
        for s in exc:
            remove_sock(s)
except Exception as e:
    logging.error(e)
    for s in inputs:
        s.close()
    server.close()
