import tensorflow as tf
import pickle
import os
import time

import utils
from setting import Setting
from data_generator import DataGenerator


base_setting = Setting()
sub_int_train_dir = base_setting.sub_int_train_dir
sub_int_valid_dir = base_setting.sub_int_valid_dir

model_save_dir = 'trained_model/double_model/'
tensorboard_log_dir = base_setting.lstm_tb_log_dir
training_log_dir = base_setting.lstm_train_log_dir

num_subset_train_data = base_setting.num_sub_train_data
num_subset_test_data = base_setting.num_sub_test_data
show_every_n = base_setting.show_every_n
save_every_n = base_setting.save_every_n
valid_every_n = base_setting.valid_every_n
num_terminal = base_setting.num_terminal


class DoubleLstmModel():
    def __init__(self,
                 num_ntoken, num_ttoken,
                 batch_size=50,
                 n_embed_dim=1500,
                 t_embed_dim=1500,
                 nt_hidden_units=1500,
                 tt_hidden_units=500,
                 learning_rate=0.001,
                 num_epochs=4,
                 time_steps=50,
                 grad_clip=5,):
        self.time_steps = time_steps
        self.batch_size = batch_size
        self.n_embed_dim = n_embed_dim
        self.num_ntoken = num_ntoken
        self.num_ttoken = num_ttoken
        self.t_embed_dim = t_embed_dim
        self.nt_hidden_units = tt_hidden_units
        self.tt_hidden_units = nt_hidden_units
        self.learning_rate = learning_rate
        self.num_epochs = num_epochs
        self.grad_clip = grad_clip

        self.build_model()

    def build_input(self):
        n_input = tf.placeholder(tf.int32, [None, None], name='n_input')
        t_input = tf.placeholder(tf.int32, [None, None], name='t_input')
        n_target = tf.placeholder(tf.int64, [None, None], name='n_target')
        t_target = tf.placeholder(tf.int64, [None, None], name='t_target')
        keep_prob = tf.placeholder(tf.float32, name='keep_prob')
        return n_input, t_input, n_target, t_target, keep_prob

    def build_input_embed(self, n_input, t_input):
        with tf.name_scope('input_embedding'):
            n_embed_matrix = tf.Variable(tf.truncated_normal(
                [self.num_ntoken, self.n_embed_dim]), name='n_embed_matrix')
            t_embed_matrix = tf.Variable(tf.truncated_normal(
                [self.num_ttoken, self.t_embed_dim]), name='t_embed_matrix')
            n_input_embedding = tf.nn.embedding_lookup(n_embed_matrix, n_input)
            t_input_embedding = tf.nn.embedding_lookup(t_embed_matrix, t_input)
        return n_input_embedding, t_input_embedding

    def get_hidden_units(self, cate):
        if cate == 'nt_model':
            hidden_units = self.nt_hidden_units
        elif cate == 'tt_model':
            hidden_units = self.tt_hidden_units
        else:
            raise AttributeError
        return hidden_units

    def build_lstm(self, keep_prob, cate):
        hidden_units = self.get_hidden_units(cate)
        def get_cell():
            with tf.name_scope(str(cate)):
                cell = tf.contrib.rnn.BasicLSTMCell(hidden_units, name='lstm_cell')
                cell = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=keep_prob)
            return cell
        lstm_cell = get_cell()
        init_state = lstm_cell.zero_state(self.batch_size, dtype=tf.float32)
        return lstm_cell, init_state

    def build_dynamic_rnn(self, cell, lstm_input, lstm_state, cate):
        hidden_units = self.get_hidden_units(cate)
        with tf.variable_scope(str(cate), reuse=tf.AUTO_REUSE):
            lstm_output, final_state = tf.nn.dynamic_rnn(
                cell, lstm_input, initial_state=lstm_state)
        lstm_output = tf.concat(lstm_output, axis=1)
        lstm_output = tf.reshape(lstm_output, [-1, hidden_units])
        return lstm_output, final_state

    def build_n_output(self, lstm_output):
        with tf.variable_scope('nt_model'):
            nt_weight = tf.Variable(tf.truncated_normal(
                [self.nt_hidden_units, self.num_ntoken], stddev=0.1),name='softmax_weight')
            nt_bias = tf.Variable(tf.zeros(self.num_ntoken), name='softmax_weight')
            nonterminal_logits = tf.nn.bias_add(tf.matmul(lstm_output, nt_weight), nt_bias)
            nonterminal_output = tf.nn.softmax(logits=nonterminal_logits, name='nt_output')
        return nonterminal_logits, nonterminal_output

    def build_t_output(self, lstm_output):
        with tf.variable_scope('tt_model'):
            t_weight = tf.Variable(tf.truncated_normal(
                [self.tt_hidden_units, self.num_ttoken], stddev=0.1), name='softmax_weight')
            t_bias = tf.Variable(tf.zeros(self.num_ttoken), name='softmax_bias')
            terminal_logits = tf.matmul(lstm_output, t_weight) + t_bias
            termnial_output = tf.nn.softmax(logits=terminal_logits, name='tt_output')
        return terminal_logits, termnial_output

    def build_loss(self, n_loss, t_loss):
        loss = tf.add(n_loss, t_loss)
        return loss

    def build_nt_loss(self, n_logits, n_targets):
        n_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=n_logits, labels=n_targets)
        n_loss = tf.reduce_mean(n_loss)
        return n_loss

    def build_tt_loss(self, t_logits, t_targets):
        t_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=t_logits, labels=t_targets)
        t_loss = tf.reduce_mean(t_loss)
        return t_loss

    def build_accuracy(self, n_output, n_target, t_output, t_target):
        n_equal = tf.equal(tf.argmax(n_output, axis=1), n_target)
        t_equal = tf.equal(tf.argmax(t_output, axis=1), t_target)
        n_accuracy = tf.reduce_mean(tf.cast(n_equal, tf.float32))
        t_accuracy = tf.reduce_mean(tf.cast(t_equal, tf.float32))
        return n_accuracy, t_accuracy

    def build_optimizer(self, n_loss, t_loss):
        """分别对两个 lstm构建optimizer，但将两个loss合并，构建一个整体optimizer也是可以的"""
        self.global_step = tf.Variable(0, trainable=False)
        learning_rate = tf.train.exponential_decay(self.learning_rate, self.global_step, 10000, 0.9)
        train_vars = tf.trainable_variables()
        nt_var_list = [var for var in train_vars if var.name.startswith('nt_model')]
        tt_var_list = [var for var in train_vars if var.name.startswith('tt_model')]
        input_var_list = [var for var in train_vars if var.name.startswith('input_embedding')]
        nt_var_list.extend(input_var_list)
        tt_var_list.extend(input_var_list)
        with tf.name_scope('nt_optimizer'):
            n_optimizer = tf.train.AdamOptimizer(learning_rate)
            gradient_pair = n_optimizer.compute_gradients(n_loss, var_list=nt_var_list)
            clip_gradient_pair = []
            for grad, var in gradient_pair:
                grad = tf.clip_by_value(grad, -self.grad_clip, self.grad_clip)
                clip_gradient_pair.append((grad, var))
            n_optimizer = n_optimizer.apply_gradients(clip_gradient_pair)
        with tf.name_scope('tt_optimizer'):
            t_optimizer = tf.train.AdamOptimizer(learning_rate)
            gradient_pair = t_optimizer.compute_gradients(t_loss, var_list=tt_var_list)
            clip_gradient_pair = []
            for grad, var in gradient_pair:
                grad = tf.clip_by_value(grad, -self.grad_clip, self.grad_clip)
                clip_gradient_pair.append((grad, var))
            t_optimizer = t_optimizer.apply_gradients(clip_gradient_pair)
        return n_optimizer, t_optimizer

    def build_summary(self, summary_dict):
        for key, value in summary_dict.items():
            tf.summary.scalar(key, value)
        merged_op = tf.summary.merge_all()
        return merged_op

    def build_model(self):
        tf.reset_default_graph()
        self.n_input, self.t_input, self.n_target, self.t_target, self.keep_prob = self.build_input()
        n_input_embedding, t_input_embedding = self.build_input_embed(
            self.n_input, self.t_input)
        n_target = tf.reshape(self.n_target, [self.batch_size*self.time_steps])
        t_target = tf.reshape(self.t_target, [self.batch_size*self.time_steps])

        lstm_input = tf.add(n_input_embedding, t_input_embedding)
        nt_lstm_cell, self.nt_init_state = self.build_lstm(self.keep_prob, cate='nt_model')
        tt_lstm_cell, self.tt_init_state = self.build_lstm(self.keep_prob, cate='tt_model')
        self.nt_lstm_state = self.nt_init_state
        self.tt_lstm_state = self.tt_init_state
        nt_lstm_output, self.nt_final_state = self.build_dynamic_rnn(
            nt_lstm_cell, lstm_input, self.nt_lstm_state, cate='nt_model')
        tt_lstm_output, self.tt_final_state = self.build_dynamic_rnn(
            tt_lstm_cell, lstm_input, self.tt_lstm_state, cate='tt_model')

        n_logits, self.n_output = self.build_n_output(nt_lstm_output)
        t_logits, self.t_output = self.build_t_output(tt_lstm_output)

        self.n_loss = self.build_nt_loss(n_logits, n_target)
        self.t_loss = self.build_tt_loss(t_logits, t_target)
        self.loss = self.build_loss(self.n_loss, self.t_loss)
        self.n_accu, self.t_accu = self.build_accuracy(
            self.n_output, n_target, self.t_output, t_target)

        self.n_optimizer, self.t_optimizer= self.build_optimizer(self.n_loss, self.t_loss)

        summary_dict = {'train loss': self.loss, 'non-terminal loss': self.t_loss,
                        'terminal loss': self.t_loss, 'n_accuracy': self.n_accu,
                        't_accuracy': self.t_loss}
        self.merged_op = self.build_summary(summary_dict)

        print('lstm model has been created...')

    def train(self):
        session = tf.Session()
        saver = tf.train.Saver()
        self.generator = DataGenerator(self.batch_size, self.time_steps)
        tb_writer = tf.summary.FileWriter(tensorboard_log_dir, session.graph)
        global_step = 0
        session.run(tf.global_variables_initializer())

        for epoch in range(1, self.num_epochs+1):
            epoch_start_time = time.time()
            batch_step = 0
            n_loss_per_epoch = 0.0
            t_loss_per_epoch = 0.0
            n_accu_per_epoch = 0.0
            t_accu_per_epoch = 0.0

            subset_generator = self.generator.get_train_subset_data()
            for data in subset_generator:
                batch_generator = self.generator.get_batch(data_seq=data)
                nt_lstm_state = session.run(self.nt_init_state)
                tt_lstm_state = session.run(self.tt_init_state)
                for b_nt_x, b_nt_y, b_tt_x, b_tt_y in batch_generator:
                    batch_step += 1
                    global_step += 1
                    batch_start_time = time.time()

                    feed = {self.t_input: b_tt_x,
                            self.n_input: b_nt_x,
                            self.n_target: b_nt_y,
                            self.t_target: b_tt_y,
                            self.keep_prob: 0.5,
                            self.nt_lstm_state: nt_lstm_state,
                            self.tt_lstm_state: tt_lstm_state,
                            self.global_step:global_step}
                    loss, n_loss, t_loss, n_accu, t_accu, _, __, summary_str = \
                        session.run([
                            self.loss,
                            self.n_loss,
                            self.t_loss,
                            self.n_accu,
                            self.t_accu,
                            self.n_optimizer,
                            self.t_optimizer,
                            self.merged_op], feed_dict=feed)
                    tb_writer.add_summary(summary_str, global_step)
                    tb_writer.flush()
                    n_loss_per_epoch += n_loss
                    t_loss_per_epoch += t_loss
                    n_accu_per_epoch += n_accu
                    t_accu_per_epoch += t_accu
                    batch_end_time = time.time()

                    if global_step % show_every_n == 0:
                        log_info = 'epoch:{}/{}  '.format(epoch, self.num_epochs) + \
                                   'global_step:{}  '.format(global_step) + \
                                   'loss:{:.2f}(n_loss:{:.2f} + t_loss:{:.2f})  '.format(n_loss+t_loss, n_loss, t_loss) + \
                                   'nt_accu:{:.2f}%  '.format(n_accu * 100) + \
                                   'tt_accu:{:.2f}%  '.format(t_accu * 100) + \
                                   'time cost per batch:{:.2f}/s'.format(batch_end_time - batch_start_time)
                        self.print_and_log(log_info)

                    if global_step % valid_every_n == 0:
                        self.valid(session, epoch, global_step)

                    if global_step % save_every_n == 0:
                        model_save_dir = model_save_dir + 'e{}_b{}.ckpt'.format(epoch, batch_step)
                        saver.save(session, model_save_dir)
                        print('model saved: epoch:{} global_step:{}'.format(epoch, global_step))

                epoch_end_time = time.time()
                epoch_cost_time = epoch_end_time - epoch_start_time
                epoch_log = 'EPOCH:{}/{}  '.format(epoch, self.num_epochs) + \
                            'time cost this epoch:{:.2f}/s  '.format(epoch_cost_time) + \
                            'epoch average n_loss:{:.2f}  '.format(n_loss_per_epoch / batch_step) + \
                            'epoch average t_loss:{:.2f}  '.format(t_loss_per_epoch / batch_step) + \
                            'epoch average nt_accu:{:.2f}%  '.format(100 * n_accu_per_epoch / batch_step) + \
                            'epoch average tt_accu:{:.2f}%  '.format(100 * t_accu_per_epoch / batch_step)
                self.print_and_log(epoch_log)

            model_save_dir = model_save_dir  + 'lastest_model.ckpt'
            saver.save(session, model_save_dir)
            self.print_and_log('model training finished...')
            session.close()

    def valid(self, session, epoch, global_step):
        valid_dir = sub_int_valid_dir + 'int_part1.json'
        with open(valid_dir, 'rb') as f:
            valid_data = pickle.load(f)
        batch_generator = self.generator.get_batch(valid_data)
        valid_step = 0
        valid_n_accuracy = 0.0
        valid_t_accuracy = 0.0
        valid_times = 400
        nt_lstm_state = session.run(self.nt_init_state)
        tt_lstm_state = session.run(self.tt_init_state)
        valid_start_time = time.time()
        for b_nt_x, b_nt_y, b_tt_x, b_tt_y in batch_generator:
            valid_step += 1
            feed = {self.t_input: b_tt_x,
                    self.n_input: b_nt_x,
                    self.n_target: b_nt_y,
                    self.t_target: b_tt_y,
                    self.keep_prob: 0.5,
                    self.nt_lstm_state: nt_lstm_state,
                    self.tt_lstm_state: tt_lstm_state,
                    self.global_step: global_step}
            n_accu, t_accu, nt_lstm_state, tt_lstm_state = session.run(
                [self.n_accu, self.t_accu, self.nt_final_state, self.tt_final_state], feed)
            valid_n_accuracy += n_accu
            valid_t_accuracy += t_accu
            if valid_step >= valid_times:
                break

        valid_n_accuracy /= valid_step
        valid_t_accuracy /= valid_step
        valid_end_time = time.time()
        valid_log = "VALID epoch:{}/{}  ".format(epoch, self.num_epochs) + \
                    "global step:{}  ".format(global_step) + \
                    "valid_nt_accu:{:.2f}%  ".format(valid_n_accuracy * 100) + \
                    "valid_tt_accu:{:.2f}%  ".format(valid_t_accuracy * 100) + \
                    "valid time cost:{:.2f}s".format(valid_end_time - valid_start_time)
        self.print_and_log(valid_log)

    def print_and_log(self, info):
        if not os.path.exists(training_log_dir):
            self.log_file = open(training_log_dir, 'w')
        self.log_file.write(info)
        self.log_file.write('\n')
        print(info)


if __name__ == '__main__':
    num_non_terminal = base_setting.num_non_terminal
    num_terminal = base_setting.num_terminal
    model = DoubleLstmModel(num_non_terminal, num_terminal)
    model.train()
