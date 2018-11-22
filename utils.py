import numpy as np
import pandas as pd
import pickle
import json
from collections import Counter


js_test_data_dir = 'js_dataset/js_programs_eval.json'  # 原始AST测试数据路径
js_train_data_dir = 'js_dataset/js_programs_training.json'  # 原始AST训练数据路径

data_parameter_dir = 'split_js_data/parameter.p'  # 生成的int-token映射字典保存路径
train_subset_dir = 'split_js_data/train_data/'  # 原始AST训练数据被分成成多个小数据集的保存路径
test_subset_dir = 'split_js_data/eval_data/'  # 原始AST测试数据被分成成多个小数据集的保存路径

most_common_termial_num = 30000


def dataset_split(is_training=True, subset_size=5000):
    '''
    读取原始AST数据集，并将其分割成多个subset data
    对每个AST，将其转换成二叉树的形式，然后进行中序遍历生成一个nt-sequence
    '''
    if is_training:
        data_path = js_train_data_dir
        total_size = 100000
        saved_to_path = train_subset_dir
    else:
        data_path = js_test_data_dir
        total_size = 50000
        saved_to_path = test_subset_dir

    file = open(data_path, 'r')
    subset_list = []
    error_count = 0
    for i in range(1, total_size + 1):
        try:
            line = file.readline()
            line = json.loads(line)
            nt_seq = ast_to_seq(line)
        except BaseException:
            error_count += 1

        subset_list.append(nt_seq)
        if i % subset_size == 0:
            sub_path = saved_to_path + \
                'part{}'.format(i // subset_size) + '.json'
            save_file = open(sub_path, 'wb')
            pickle.dump(subset_list, save_file)
            subset_list = []
            print(
                'nt_sequence part{} has been saved...'.format(
                    i // subset_size))

    if is_training:  # 当处理训练数据集时，需要保存映射map
        save_string_int_dict()
        print('training data seperating finished...')
        print('encoding information has been save in {}'.format(data_parameter_dir))
    else:
        print('testing data seperating finished...')


def load_data_with_pickle(path='split_js_data/train_data/part1.json'):
    file = open(path, 'rb')
    data = pickle.load(file)
    return data


def add_two_bits_info(node, brother_map):
    # 向每个节点添加两bit的额外信息：isTerminal和hasSibling
    if 'children' in node.keys():
        node['isTerminal'] = False
    else:
        node['isTerminal'] = True
    if brother_map.get(node['id'], -1) == -1:
        node['hasSibling'] = False
    else:
        node['hasSibling'] = True


def bulid_binary_tree(data):
    '''
    transform the AST(one node may have several childNodes) to
    Left-Child-Right-Sibling(LCRS) binary tree.
    '''
    brother_map = {0: -1}
    for index, node in enumerate(data):  # 顺序遍历每个AST中的node
        if not isinstance(node, dict) and node == 0:  # AST中最后添加一个'EOF’标识
            data[index] = 'EOF'
            return data
        # 向每个节点添加两bit的额外信息
        add_two_bits_info(node, brother_map)
        node['right'] = brother_map.get(node['id'], -1)
        # 表示该node为non-terminal
        if 'children' in node.keys():
            child_list = node['children']
            node['left'] = child_list[0]  # 构建该node的left node
            for i, bro in enumerate(
                    child_list):  # 为该node的所有children构建right sibling
                if i == len(child_list) - 1:
                    break
                brother_map[bro] = child_list[i + 1]
            node.pop('children')
    return data


def get_test_ast():
    ast_example = [{'id': 0, 'type': 'Program', 'children': [1]},
                   {'id': 1, 'type': 'ExpressionStatement', 'children': [2]},
                   {'id': 2, 'type': 'CallExpression', 'children': [3, 8, 9, 10]},
                   {'id': 3, 'type': 'MemberExpression', 'children': [4, 7]},
                   {'id': 4, 'type': 'MemberExpression', 'children': [5, 6]},
                   {'id': 5, 'type': 'Identifier', 'value': 'CKEDITOR'},
                   {'id': 6, 'type': 'Property', 'value': 'plugins'},
                   {'id': 7, 'type': 'Property', 'value': 'setLang'},
                   {'id': 8, 'type': 'LiteralString', 'value': 'iframe'},
                   {'id': 9, 'type': 'LiteralString', 'value': 'ka'},
                   {'id': 10, 'type': 'ObjectExpression', 'children': [11, 13, 15, 17, 19]},
                   {'id': 11, 'type': 'Property', 'value': 'border', 'children': [12]},
                   {'id': 12, 'type': 'LiteralString', 'value': 'ჩარჩოს გამოჩენა'},
                   {'id': 13, 'type': 'Property', 'value': 'noUrl', 'children': [14]},
                   {'id': 14, 'type': 'LiteralString', 'value': 'აკრიფეთ iframe-ის URL'},
                   {'id': 15, 'type': 'Property', 'value': 'scrolling', 'children': [16]},
                   {'id': 16, 'type': 'LiteralString', 'value': 'გადახვევის ზოლების დაშვება'},
                   {'id': 17, 'type': 'Property', 'value': 'title', 'children': [18]},
                   {'id': 18, 'type': 'LiteralString', 'value': 'IFrame-ის პარამეტრები'},
                   {'id': 19, 'type': 'Property', 'value': 'toolbar', 'children': [20]},
                   {'id': 20, 'type': 'LiteralString', 'value': 'IFrame'}, 0]
    return ast_example


terminalCountMap = Counter()
nonTerminalSet = set()


def ast_to_seq(data):
    bi_tree = bulid_binary_tree(data)

    def node_to_string(node):
        if node == 'EMPTY':
            string_node = 'EMPTY'
        elif node['isTerminal']:  # 如果node为terminal
            string_node = str(node['type']) + '=$$=' + \
                str(node['value'])  # + '==' + str(node['id'])
            terminalCountMap[string_node] += 1
        else:  # 如果是non-terminal
            string_node = str(node['type']) + '=$$=' + \
                str(node['hasSibling']) + '=$$=' + \
                str(node['isTerminal'])  # + '==' +str(node['id'])
            # if 'value' in node.keys():
            #     string_node += '=$$=' + str(node['value'])
            nonTerminalSet.add(string_node)
        return string_node

    def in_order_traversal(data, index):
        node = data[index]
        if 'left' in node.keys():
            in_order_traversal(data, node['left'])
        # 如果该节点为non-terminal，则构建NT-pair并加入到sequence中。
        if 'isTerminal' in node.keys() and node['isTerminal'] == False:
            '''如果该node是non-terminal
            如果该non-terminal包含一个terminal 子节点，则和该子节点组成nt_pair保存在output中
            否则将nt_pair的T设为字符串EMPTY'''
            n_pair = node_to_string(node)
            t_pair = None
            if data[node['left']]['isTerminal']:
                assert data[node['left']]['id'] == node['left']
                t_pair = node_to_string(data[node['left']])
            else:
                t_pair = node_to_string('EMPTY')
            nt_pair = (n_pair, t_pair)
            output.append(nt_pair)
        else:
            node_to_string(node)
        # 遍历right side
        if node['right'] != -1:
            in_order_traversal(data, node['right'])

    output = []
    in_order_traversal(bi_tree, 0)
    return output


def save_string_int_dict():
    '''
    将nonterminal和terminal对应的映射字典保存并返回
    其中，对于terminal只选用most frequent的30000个token
    :return:
    '''
    tt_token_to_int = {}
    tt_int_to_token = {}
    nt_token_to_int = {}
    nt_int_to_token = {}

    most_common_tuple = terminalCountMap.most_common(most_common_termial_num)
    for index, (token, times) in enumerate(most_common_tuple):
        tt_token_to_int[token] = index
        tt_int_to_token[index] = token
    for index, token in enumerate(list(nonTerminalSet)):
        nt_token_to_int[token] = index
        nt_int_to_token[index] = token
    # terminal中添加UNK
    tt_int_to_token[len(tt_int_to_token)] = 'UNK'
    tt_token_to_int['UNK'] = len(tt_token_to_int)
    # 保存到本地
    with open(data_parameter_dir, 'wb') as file:
        pickle.dump([tt_token_to_int, tt_int_to_token,
                     nt_token_to_int, nt_int_to_token], file)
    return tt_token_to_int, tt_int_to_token, nt_token_to_int, nt_int_to_token


def load_dict_parameter():
    '''加载terminal和nonterminal对应的映射字典'''
    file = open(data_parameter_dir, 'rb')
    tt_token_to_int, tt_int_to_token, nt_token_to_int, nt_int_to_token = pickle.load(
        file)
    return tt_token_to_int, tt_int_to_token, nt_token_to_int, nt_int_to_token


def process_nt_sequence(time_steps=50):
    '''
    对已经处理好的NT seq进行进一步的处理，
    首先将每个token转换为number，然后截取各个seq成50的倍数，（50为time-steps大小）
    然后将每个AST都拼接到一起，
    '''
    tt_token_to_int, tt_int_to_token, nt_token_to_int, nt_int_to_token = load_dict_parameter()
    num_subset_train_data = 20
    subset_data_dir = 'split_js_data/train_data/'
    total_num_nt_pair = 0

    def get_subset_data():  # 对每个part的nt_sequence读取并返回，等待进行处理
        for i in range(1, num_subset_train_data + 1):
            data_path = subset_data_dir + 'part{}.json'.format(i)
            file = open(data_path, 'rb')
            data = pickle.load(file)
            yield (i, data)

    subset_generator = get_subset_data()
    for index, data in subset_generator:
        #        data = pickle.load(open(subset_data_dir+'part1.json', 'rb'))
        data_seq = []
        for one_ast in data:  # 将每个nt_seq进行截取，并encode成integer，然后保存
            # 将每个nt seq都切割成time steps的整数倍
            num_steps = len(one_ast) // time_steps
            if num_steps == 0:  # 该ast大小不足time step 舍去
                continue
            one_ast = one_ast[:num_steps * time_steps]
            nt_int_seq = [
                (nt_token_to_int[n],
                 tt_token_to_int.get(
                    t,
                    tt_token_to_int['UNK'])) for n,
                t in one_ast]
            data_seq.extend(nt_int_seq)
        print(len(data_seq))
        total_num_nt_pair += len(data_seq)
        with open(subset_data_dir + 'int_format/int_part{}.json'.format(index), 'wb') as file:
            pickle.dump(data_seq, file)
            print(
                'part{} of nt_seq data has been encoded into integer and saved...'.format(index))
    print('There are {} of nt_pair in train data set...'.format(
        total_num_nt_pair))  # total == 6970900


def test_nt_seq_to_int():
    '''
    读入已经被分割并处理成nt sequence的test data，
    然后根据处理training数据时生成的token2int映射字典将其转换成对应的int sequence
    :return:
    '''
    tt_token_to_int, tt_int_to_token, nt_token_to_int, nt_int_to_token = load_dict_parameter()
    num_subset_train_data = 10
    subset_data_dir = 'split_js_data/eval_data/'
    total_num_nt_pair = 0

    def get_subset_data():  # 对每个part的nt_sequence读取并返回，等待进行处理
        for i in range(1, num_subset_train_data + 1):
            data_path = subset_data_dir + 'part{}.json'.format(i)
            file = open(data_path, 'rb')
            data = pickle.load(file)
            yield (i, data)

    subset_generator = get_subset_data()
    for index, data in subset_generator:
        data_seq = []
        num_nt_pair = 0
        for one_ast in data:  # 将每个由token组成的nt_seq，并encode成integer，然后保存
            nt_int_seq = [
                (nt_token_to_int[n],
                 tt_token_to_int.get(
                    t,
                    tt_token_to_int['UNK'])) for n,
                t in one_ast]
            data_seq.append(nt_int_seq)
            num_nt_pair += len(nt_int_seq)
        print('the number of nt_pair in this part-set data is {}'.format(num_nt_pair))
        total_num_nt_pair += num_nt_pair

        with open(subset_data_dir + 'int_format/int_part{}.json'.format(index), 'wb') as file:
            pickle.dump(data_seq, file)
            print(
                'part{} of nt_seq data has been encoded into integer and saved...'.format(index))
    print('There are {} of nt_pair in test data set...'.format(
        total_num_nt_pair))  # 4706813


if __name__ == '__main__':
    training_data_process = False
    if training_data_process:
        dataset_split(is_training=True)
        process_nt_sequence()
    else:
        #    dataset_split(is_training=False)
        test_nt_seq_to_int()
