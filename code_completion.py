import tensorflow as tf
import random
import time
import pickle

from lstm_model import RnnModel
from data_generator import DataGenerator
from setting import Setting
import utils

test_setting = Setting()
model_save_dir = test_setting.lstm_model_save_dir
show_every_n = test_setting.test_show
completion_log_dir = test_setting.lstm_completion_log_dir
unknown_token = test_setting.unknown_token
define_topk = test_setting.define_topk


class CodeCompletion(object):
    """test the performance of code completion, Creating a random hole in the given nt-sequence,
    and the model will return it's prediction, then calculate the accuracy"""

    def __init__(self,
                 num_ntoken,
                 num_ttoken, ):
        self.model = RnnModel(num_ntoken, num_ttoken, is_training=False)
        self.log_file = open(completion_log_dir, 'w')
        self.tt_token_to_int, self.tt_int_to_token, self.nt_token_to_int, self.nt_int_to_token = \
            utils.load_dict_parameter()
        self.session = tf.Session()
        checkpoints_path = tf.train.latest_checkpoint(model_save_dir)
        saver = tf.train.Saver()
        saver.restore(self.session, checkpoints_path)
        self.test_log(checkpoints_path + ' is using...')

    def predict(self, pre_context, topk=3):
        """对外接口，先将所有pre-context转换为int，然后使用trained model进行evaluate"""
        nt_seq = utils.one_ast_to_seq(pre_context)
        int_nt_seq = []
        for n_token, t_token in nt_seq:
            n_int = self.nt_token_to_int[n_token]
            t_int = self.tt_token_to_int.get(t_token, unknown_token)
            int_nt_seq.append((n_int, t_int))
        if define_topk == topk:
            n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss = self.eval(int_nt_seq)
        else:
            n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss = self.eval_without_define_k(int_nt_seq, topk)

        topk_token_pairs = [self.int_to_token(n_int ,t_int)
                            for n_int, t_int in zip(n_topk_pred, t_topk_pred)]
        topk_pairs_poss = [(n_poss, t_poss)
                           for n_poss, t_poss in zip(n_topk_poss, t_topk_poss)]

        print('the token you may want to write is:')
        print(topk_token_pairs)
        print('with possibilities:')
        print(topk_pairs_poss)
        return topk_token_pairs, topk_pairs_poss

    def eval(self, prefix):
        """ evaluate one source code file, return the top k prediction and it's possibilities,
        Input: all tokens before the hole token(prefix) and all tokens after the hole token,
        ML model will predict the most probable token in the hole
        """
        lstm_state = self.session.run(self.model.init_state)
        test_batch = self.generator.get_test_batch(prefix)
        n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss = None, None, None, None
        for nt_token, tt_token in test_batch:
            feed = {self.model.n_input: nt_token,
                    self.model.t_input: tt_token,
                    self.model.keep_prob: 1.,
                    self.model.lstm_state: lstm_state}
            n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss, lstm_state = self.session.run([
                self.model.n_topk_pred, self.model.n_topk_poss, self.model.t_topk_pred,
                self.model.t_topk_poss, self.model.final_state], feed_dict=feed)

        assert n_topk_pred is not None and n_topk_poss is not None and \
               t_topk_pred is not None and t_topk_poss is not None
        n_topk_pred = n_topk_pred[-1, :]
        n_topk_poss = n_topk_poss[-1, :]
        t_topk_pred = t_topk_pred[-1, :]
        t_topk_poss = t_topk_poss[-1, :]

        topk_token_pairs = [self.int_to_token(n_int ,t_int)
                            for n_int, t_int in zip(n_topk_pred, t_topk_pred)]
        topk_pairs_poss = [(n_poss, t_poss)
                           for n_poss, t_poss in zip(n_topk_poss, t_topk_poss)]

        print('\nthe token you may want to write is:')
        for index, (token, poss) in enumerate(zip(topk_token_pairs, topk_pairs_poss)):
            n_token, t_token = token
            n_poss, t_poss = poss
            print('top{} n_token:{} with possibility:{:.2f}'.format(index+1, n_token, n_poss))
            print('top{} t_token:{} with possibility:{:.2f}'.format(index+1, t_token, t_poss))
        return n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss

    def eval_without_define_k(self, prefix, topk):
        """ evaluate one source code file, return the top k prediction and it's possibilities,
        Input: all tokens before the hole token(prefix) and all tokens after the hole token,
        ML model will predict the most probable token in the hole
        """
        lstm_state = self.session.run(self.model.init_state)
        test_batch = self.generator.get_test_batch(prefix)
        n_prediction, t_prediction = None, None
        for nt_token, tt_token in test_batch:
            feed = {self.model.n_input: nt_token,
                    self.model.t_input: tt_token,
                    self.model.keep_prob: 1.,
                    self.model.lstm_state: lstm_state}
            n_prediction, t_prediction, lstm_state = self.session.run(
                [self.model.n_output, self.model.t_output, self.model.final_state], feed_dict=feed)

        assert n_prediction is not None and t_prediction is not None
        n_prediction = n_prediction[-1, :]
        t_prediction = t_prediction[-1, :]
        n_topk_pred = (-n_prediction).argsort()[:topk]
        t_topk_pred = (-t_prediction).argsort()[:topk]
        n_topk_poss = n_prediction[n_topk_pred]
        t_topk_poss = t_prediction[t_topk_pred]

        return n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss

    def query(self, token_sequence, topk=3):
        prefix, expectation, suffix = self.create_hole(token_sequence)  # 随机在sequence中创建一个hole
        n_expectation, t_expectation = expectation[0]
        if define_topk == topk:
            n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss = self.eval(prefix)
        else:
            n_topk_pred, n_topk_poss, t_topk_pred, t_topk_poss = self.eval_without_define_k(prefix, topk)

        if self.top_one_equal(n_topk_pred, n_expectation):
            self.nt_correct_count += 1
        else:
            temp_error_dic = {}
            temp_error_dic['ast_prefix'] = prefix
            temp_error_dic['ast_expectation'] = expectation
            temp_error_dic['ast_suffix'] = suffix
            temp_error_dic['expectation'] = n_expectation
            temp_error_dic['prediction'] = n_topk_pred
            self.nt_error_log.append(temp_error_dic)

        if self.top_one_equal(t_topk_pred, t_expectation):
            self.tt_correct_count += 1
        else:
            temp_error_dic = {}
            temp_error_dic['ast_prefix'] = prefix
            temp_error_dic['ast_expectation'] = expectation
            temp_error_dic['ast_suffix'] = suffix
            temp_error_dic['expectation'] = t_expectation
            temp_error_dic['prediction'] = t_topk_pred
            self.tt_error_log.append(temp_error_dic)

        if self.topk_equal(n_topk_pred, n_expectation):
            self.topk_nt_correct_count += 1
        if self.topk_equal(t_topk_pred, t_expectation):
            self.topk_tt_correct_count += 1

    def completion_test(self, topk=3):
        """Test model with the whole test dataset
        first, it will create a hole in the test ast_nt_sequence randomly,
        then, it will call self.query() for each test case,
        finally, the statistical accuracy will be update
        """
        self.test_log('test phase is beginning...')
        start_time = time.time()
        self.nt_error_log = []
        self.tt_error_log = []
        self.tt_correct_count = 0.0
        self.nt_correct_count = 0.0
        self.topk_nt_correct_count = 0.0
        self.topk_tt_correct_count = 0.0
        test_times = 2000
        test_step = 0
        self.generator = DataGenerator()
        sub_data_generator = self.generator.get_test_subset_data()

        for index, subset_test_data in sub_data_generator:  # 遍历每个sub test dataset
            one_test_start_time = time.time()
            for token_sequence in subset_test_data:  # 遍历该subset中每个nt token sequence
                test_step += 1
                # 对一个ast sequence进行test
                self.query(token_sequence, topk=topk)
                if test_step % show_every_n == 0:
                    one_test_end_time = time.time()
                    duration = (one_test_end_time - one_test_start_time) / show_every_n
                    one_test_start_time = one_test_end_time
                    nt_accu = self.nt_correct_count / test_step
                    tt_accu = self.tt_correct_count / test_step
                    topk_nt_accu = self.topk_nt_correct_count / test_step
                    topk_tt_accu = self.topk_tt_correct_count / test_step
                    log_info = 'test step:{}  '.format(test_step) + \
                               'nt_accuracy:{:.2f}%  '.format(nt_accu * 100) + \
                               'tt_accuracy:{:.2f}%  '.format(tt_accu * 100) + \
                               'nt_top{}_accuracy:{:.2f}%  '.format(define_topk, topk_nt_accu * 100) + \
                               'tt_top{}_accuracy:{:.2f}%  '.format(define_topk, topk_tt_accu * 100) + \
                               'average time cost:{:.2f}s  '.format(duration)
                    self.test_log(log_info)

                if test_step >= test_times:
                    break

            nt_accuracy = self.nt_correct_count / test_step
            tt_accuracy = self.tt_correct_count / test_step
            topk_nt_accu = self.topk_nt_correct_count / test_step
            topk_tt_accu = self.topk_tt_correct_count / test_step
            end_time = time.time()
            log_info = '{}th subset of test data  '.format(index) + \
                       'there are {} nt_sequence to test  '.format(test_step) + \
                       'accuracy of non-terminal token: {:.2f}%  '.format(nt_accuracy * 100) + \
                       'accuracy of terminal token: {:.2f}%  '.format(tt_accuracy * 100) + \
                       'top{} accuracy of non-terminal:{:.2f}%  '.format(define_topk, topk_nt_accu * 100) + \
                       'top{} accuracy of terminal:{:.2f}%  '.format(define_topk, topk_tt_accu * 100) + \
                       'total time cost of this subset: {:.2f}s  '.format(end_time - start_time) + \
                       'average time cost per case: {:.2f}s  '.format((end_time - start_time) / test_step)
            self.test_log(log_info)

        error_prediction_dir = 'error_prediction_info.p'
        file = open(error_prediction_dir, 'wb')
        pickle.dump((self.nt_error_log, self.tt_error_log), file)
        print(error_prediction_dir, 'has been saved...')

    def top_one_equal(self, prediction, expectation):
        if prediction[0] == expectation:
            return True
        return False

    def topk_equal(self, prediction, expectation):
        if expectation in prediction:
            return True
        return False

    def create_hole(self, nt_token_seq, hole_size=1):
        hole_start_index = random.randint(
            len(nt_token_seq) // 2, len(nt_token_seq) - hole_size)
        hole_end_index = hole_start_index + hole_size
        prefix = nt_token_seq[0:hole_start_index]
        expectation = nt_token_seq[hole_start_index:hole_end_index]
        suffix = nt_token_seq[hole_end_index:-1]
        return prefix, expectation, suffix

    def test_log(self, log_info):
        self.log_file.write(log_info)
        self.log_file.write('\n')
        print(log_info)

    def int_to_token(self, n_int, t_int):
        """将以int形式表示的n_token和t_token还原成对应的token信息"""
        n_token = self.nt_int_to_token[n_int].split(test_setting.split_token)
        t_token = self.tt_int_to_token[t_int].split(test_setting.split_token)
        n_token_present = {}
        t_token_present = {}
        for index, value in enumerate(n_token):
            n_token_present[index] = value
        if t_token[0] == test_setting.unknown_token:
            t_token_present[0] = 'Unknown Token'
        else:
            for index, value in enumerate(t_token):
                t_token_present[index] = value
        return n_token_present, t_token_present




if __name__ == '__main__':
    num_ntoken = test_setting.num_non_terminal
    num_ttoken = test_setting.num_terminal
    test_model = CodeCompletion(num_ntoken, num_ttoken)
    test_model.completion_test(topk=3)
