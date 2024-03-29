import copy


STARTM = [
    [1, 2, 3],  # 0
    [1, 2, 4],  # 1
    [1, 3, 5],  # 2
    [1, 4, 6],  # 3
    [1, 5, 7],  # 4
    [1, 6, 8],  # 5
    [1, 7, 9],  # 6
    [1, 8, 10],  # 7
    [1, 9, 11],  # 8
    [1, 10, 12],  # 9
    [1, 11, 12],  # 10
    [2, 3],  # 11
    [2, 4],  # 12
    [2], [2], [2], [2], [2], [2], [2],  # 13-19
    [3, 4],  # 20
    [3, 4],  # 21
    [3], [3], [3], [3], [3], [3],  # 22-27
    [4], [4], [4], [4], [4], [4],  # 28-33
    [], [], [], [], [], [], [], [], [], []  # 34-43
]

FV_COUNT = 11
F_COUNT = 12
V_COUNT = 44


def send_msg(s, msg):
    data_to_send = len(msg).to_bytes(4, 'little') + bytes(msg, 'utf-8')
    # print(data_to_send)
    try:
        s.send(data_to_send)
    except Exception:
        return False
    else:
        return True


def is_common(m1, m2):
    ''' returns true if ther is an edge '''
    if len(m1) < 3 or len(m2) < 3:
        return False
    p1 = 0
    p2 = 0
    eqs = 0
    while p1 < 3 and p2 < 3:
        if m1[p1] == m2[p2]:
            eqs += 1
            p1 += 1
            p2 += 1
        elif m1[p1] > m2[p2]:
            p2 += 1
        else:
            p1 += 1
    return True if eqs == 2 else False


def test_loop_bfs(matrix, ind, f):
    ''' test for loop before adding f to M[ind] '''
    if len(matrix[ind]) < 2:
        return True
    q = []
    startq = 0
    prev = [None] * len(matrix)
    w = [-1] * len(matrix)
    w[ind] = 0
    # fill q
    new_m = sorted(matrix[ind] + [f])
    for i in range(0, len(matrix) - 1):
        if is_common(new_m, matrix[i]):
            w[i] = 1
            q.append(i)
            prev[i] = ind
    while startq < len(q):
        m0 = q[startq]
        if w[m0] > 5:
            return True
        startq += 1
        # m - взяли из fifo
        for m in range(0, len(matrix) - 1):
            if m == m0 or prev[m0] == m:
                continue
            if is_common(matrix[m0], matrix[m]):
                if w[m] > 0:
                    return False
                elif w[m] < 0:
                    q.append(m)
                    w[m] = w[m0] + 1
                    prev[m] = m0
    return True


def test_loop_in_facet(matrix, index, facet, f):
    ''' test for loop < FV_COUNT in facet 'facet' after adding f to m[index]
        return False if such loop found, else True '''
    a = matrix[index][0]
    b = matrix[index][1]
    # если поиск не в грани f
    if a == facet:
        a = f
    elif b == facet:
        b = f
    # найдём крайние точки маршрута
    i_a = None
    i_b = None
    found_count = 0
    for m_i in range(len(matrix)):
        if m_i == index:
            # пропускаем текущую
            continue
        if facet in matrix[m_i]:
            if a in matrix[m_i]:
                # must be only one
                if len(matrix[m_i]) > 2:
                    i_a = m_i
                    if found_count > 1:
                        break
                    found_count += 1
                else:
                    # вершина не заполнена - дальше пути нет
                    return True
            elif b in matrix[m_i]:  # a и b не могут быть там одновременно
                if len(matrix[m_i]) > 2:
                    i_b = m_i
                    if found_count > 1:
                        break
                    found_count += 1
                else:
                    return True

    if not i_a:
        return True

    seen = {index, i_a}  # set of seen nodes

    # теперь ищем маршрут из i_a в i_b
    route_len = 0
    f2search = a  # грань, которую будем искать
    for f0 in matrix[i_a]:
        if f0 != facet and f0 != f2search:
            f2search = f0
            break
    
    while route_len < FV_COUNT - 3:
        for i_m in range(len(matrix)):
            if i_m in seen:
                continue
            if facet in matrix[i_m] and f2search in matrix[i_m]:
                # нашли
                route_len += 1
                if i_m == i_b:
                    return False
                if len(matrix[i_m]) < 3:
                    # тупик
                    return True
                seen.add(i_m)
                for f0 in matrix[i_m]:
                    if f0 != facet and f0 != f2search:
                        f2search = f0
                        break
                break
        else:
            return True
    return True


def pairs(matrix, f):
    ''' return leaved pairs vector for facet f in matrix '''
    p = [2] * (F_COUNT + 1)
    p[0] = 0
    p[f] = 0
    for m in matrix:
        if f in m:
            for f1 in m:
                if f1 != f:
                    p[f1] -= 1
    return p


def m_to_s(matrix):
    prev_pos = [0, 0, 0, 0, 0, 4, 5, 6]  # position of last
    strings = [b'', b'', b'', b'', b'', b'', b'', b'']  # result strings
    for i in range(11, V_COUNT):
        for f in range(5, 8):
            if f in matrix[i]:
                strings[f] += (i - prev_pos[f] + 0x60).to_bytes(1, 'little')
                prev_pos[f] = i
    # lets check
    if len(strings[7]):
        if len(strings[6]) != 9 or len(strings[5]) != 9:
            raise ValueError
    elif len(strings[6]):
        if len(strings[5]) != 9:
            raise ValueError
    return strings[5] + strings[6] + strings[7]


def s_to_m(s):
    prev_pos = [0, 0, 0, 0, 0, 4, 5, 6]
    matrix = copy.deepcopy(STARTM)
    for i in range(len(s)):
        f = i // 9 + 5
        offset = s[i] - 0x60
        matrix[prev_pos[f] + offset].append(f)
        prev_pos[f] += offset
    return matrix
