import tensorflow as tf
import pickle
import numpy as np
import time

import utils



subset_int_data_dir = 'split_js_data/train_data/int_format/'
model_save_dir = 'trained_model/lstm_model/'
tensorboard_log_dir = 'tensorboard_log/lstm/'
curr_time = time.strftime('_%Y_%M_%d_%H', time.localtime())
training_log_dir = 'training_log/lstm_log'+str(curr_time) + '.txt'

num_subset_train_data = 20
num_subset_test_data = 10
show_every_n = 100
save_every_n = 1500
num_terminal = 30000

class LSTM_Model(object):
    def __init__(self,
                 num_ntoken, num_ttoken, is_training=True, is_log=False,
                 batch_size=64,
                 n_embed_dim=64,
                 t_embed_dim=200,
                 num_hidden_units=256,
                 num_hidden_layers=2,
                 learning_rate=0.001,
                 num_epoches=12,
                 time_steps=50, ):
        self.time_steps = time_steps
        self.batch_size = batch_size
        self.n_embed_dim = n_embed_dim
        self.num_ntoken = num_ntoken
        self.num_ttoken = num_ttoken
        self.t_embed_dim = t_embed_dim
        self.num_hidden_units = num_hidden_units
        self.num_hidden_layers = num_hidden_layers
        self.learning_rate = learning_rate
        self.num_epoches = num_epoches
        self.is_log = is_log

        if is_training == False:
            self.batch_size = 1
            self.time_steps = 1

        self.build_model()

    def build_input(self):
        n_input = tf.placeholder(tf.int32, [self.batch_size, self.time_steps], name='n_input')
        t_input = tf.placeholder(tf.int32, [self.batch_size, self.time_steps], name='t_input')
        n_target = tf.placeholder(tf.int32, [self.batch_size, self.time_steps], name='n_target')
        t_target = tf.placeholder(tf.int32, [self.batch_size, self.time_steps], name='t_target')
        keep_prob = tf.placeholder(tf.float32, name='keep_prob')
        return n_input, t_input, n_target, t_target, keep_prob

    def build_input_embed(self, n_input, t_input):
        n_embed_matrix = tf.Variable(tf.truncated_normal(
            [self.num_ntoken, self.n_embed_dim]), name='n_embed_matrix')
        t_embed_matrix = tf.Variable(tf.truncated_normal(
            [self.num_ttoken, self.t_embed_dim]), name='t_embed_matrix')
        n_input_embedding = tf.nn.embedding_lookup(n_embed_matrix, n_input)
        t_input_embedding = tf.nn.embedding_lookup(t_embed_matrix, t_input)
        return n_input_embedding, t_input_embedding

    def build_lstm(self, keep_prob):
        def lstm_cell():
            cell = tf.contrib.rnn.BasicLSTMCell(self.num_hidden_units)
            cell = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=keep_prob)
            return cell
        cell_list = [lstm_cell() for _ in range(self.num_hidden_layers)]
        cells = tf.contrib.rnn.MultiRNNCell(cell_list)
        init_state = cells.zero_state(self.batch_size, dtype=tf.float32)
        return cells, init_state

    def build_n_output(self, lstm_output):
        # 将lstm_output的形状由[batch_size, time_steps, n_units] 转换为 [batch_size*time_steps, n_units]
        seq_output = tf.concat(lstm_output, axis=1)
        seq_output = tf.reshape(seq_output, [-1, self.num_hidden_units])

        with tf.variable_scope('non_terminal_softmax'):
            nt_weight = tf.Variable(tf.truncated_normal([self.num_hidden_units, self.num_ntoken], stddev=0.1))
            nt_bias = tf.Variable(tf.zeros(self.num_ntoken))

        nonterminal_logits = tf.matmul(seq_output, nt_weight) + nt_bias
        nonterminal_output = tf.nn.softmax(logits=nonterminal_logits, name='nonterminal_output')
        return nonterminal_logits, nonterminal_output

    def build_t_output(self, lstm_output):
        # 将lstm_output的形状由[batch_size, time_steps, n_units] 转换为 [batch_size*time_steps, n_units]
        seq_output = tf.concat(lstm_output, axis=1)
        seq_output = tf.reshape(seq_output, [-1, self.num_hidden_units])
        with tf.variable_scope('terminal_softmax'):
            t_weight = tf.Variable(tf.truncated_normal([self.num_hidden_units, self.num_ttoken], stddev=0.1))
            t_bias = tf.Variable(tf.zeros(self.num_ttoken))

        terminal_logits = tf.matmul(seq_output, t_weight) + t_bias
        termnial_output = tf.nn.softmax(logits=terminal_logits, name='terminal_output')
        return terminal_logits, termnial_output



    def build_loss(self, n_logits, n_target, t_logits, t_target):
        # todo: 使用负采样方法进行训练加快训练速度？
        n_loss = tf.nn.softmax_cross_entropy_with_logits_v2(logits=n_logits, labels=n_target)
        t_loss = tf.nn.softmax_cross_entropy_with_logits_v2(logits=t_logits, labels=t_target)
        loss = tf.add(n_loss, t_loss)
        loss = tf.reduce_mean(loss)
        return loss, n_loss, t_loss

    def bulid_accuracy(self, n_output, n_target, t_output, t_target):
        n_equal = tf.equal(tf.argmax(n_output, axis=1), tf.argmax(n_target, axis=1))
        t_equal = tf.equal(tf.argmax(t_output, axis=1), tf.argmax(t_target, axis=1))
        n_accuracy = tf.reduce_mean(tf.cast(n_equal, tf.float32))
        t_accuracy = tf.reduce_mean(tf.cast(t_equal, tf.float32))
        return n_accuracy, t_accuracy

    def bulid_optimizer(self, loss):
        optimizer = tf.train.AdamOptimizer(self.learning_rate)
        gradient_pair = optimizer.compute_gradients(loss)
        clip_gradient_pair = []
        for grad, var in gradient_pair:
            grad = tf.clip_by_value(grad, -2, 2)
            clip_gradient_pair.append((grad, var))
        optimizer = optimizer.apply_gradients(clip_gradient_pair)
        return optimizer

    def bulid_onehot_target(self, n_target, t_target, n_shape, t_shape):
        onehot_n_target = tf.one_hot(n_target, self.num_ntoken)
        onehot_n_target = tf.reshape(onehot_n_target, n_shape)
        onehot_t_target = tf.one_hot(t_target, self.num_ttoken)
        onehot_t_target = tf.reshape(onehot_t_target, t_shape)
        return onehot_n_target, onehot_t_target

    def build_model(self):
        tf.reset_default_graph()
        self.n_input, self.t_input, self.n_target, self.t_target, self.keep_prob = self.build_input()
        n_input_embedding, t_input_embedding = self.build_input_embed(self.n_input, self.t_input)
        # print(n_input_embedding.get_shape()) # (64, 50, 64)
        # print(t_input_embedding.get_shape()) # (64, 50, 200)
        lstm_input = tf.concat([n_input_embedding, t_input_embedding], 2)
        # print(lstm_input.get_shape()) # (64, 50, 264)
        cells, self.init_state = self.build_lstm(self.keep_prob)
        lstm_output, self.final_state = tf.nn.dynamic_rnn(cells, lstm_input, initial_state=self.init_state)
        t_logits, self.t_output = self.build_t_output(lstm_output)
        n_logits, self.n_output = self. build_n_output(lstm_output)

        onehot_n_target, onehot_t_target = self.bulid_onehot_target(
            self.n_target, self.t_target, n_logits.get_shape(), t_logits.get_shape())

        self.loss, self.n_loss, self.t_loss = self.build_loss(
            n_logits, onehot_n_target, t_logits, onehot_t_target)
        self.n_accu, self.t_accu = self.bulid_accuracy(
            self.n_output, onehot_n_target, self.t_output, onehot_t_target)
        self.optimizer = self.bulid_optimizer(self.loss)

        tf.summary.scalar('train_loss', self.loss)
        tf.summary.scalar('n_accuracy', self.n_accu)
        tf.summary.scalar('t_accuracy', self.t_accu)
        self.merged_op = tf.summary.merge_all()

        print('lstm model has been created...')

    def get_batch(self, data_seq):
        data_seq = np.array(data_seq) # 是否可以注释掉节省时间
        total_length = self.time_steps * self.batch_size
        n_batches = len(data_seq) // total_length
        data_seq = data_seq[:total_length * n_batches]
        nt_x = data_seq[:, 0]
        tt_x = data_seq[:, 1]
        nt_y = np.zeros_like(nt_x)
        tt_y = np.zeros_like(tt_x)
        nt_y[:-1], nt_y[-1] = nt_x[1:], nt_x[0]
        tt_y[:-1], tt_y[-1] = tt_x[1:], tt_x[0]

        nt_x = nt_x.reshape((self.batch_size, -1))
        tt_x = tt_x.reshape((self.batch_size, -1))
        nt_y = nt_y.reshape((self.batch_size, -1))
        tt_y = tt_y.reshape((self.batch_size, -1))
        data_seq = data_seq.reshape((self.batch_size, -1))
        for n in range(0, data_seq.shape[1], self.time_steps):
            batch_nt_x = nt_x[:, n:n + self.time_steps]
            batch_tt_x = tt_x[:, n:n + self.time_steps]
            batch_nt_y = nt_y[:, n:n + self.time_steps]
            batch_tt_y = tt_y[:, n:n + self.time_steps]
            if batch_nt_x.shape[1] == 0:
                break
            yield batch_nt_x, batch_nt_y, batch_tt_x, batch_tt_y

    def get_subset_data(self):
        for i in range(1, num_subset_train_data + 1):
            data_path = subset_int_data_dir + 'part{}.json'.format(i)
            file = open(data_path, 'rb')
            data = pickle.load(file)
            yield data

    def train(self):
        saver = tf.train.Saver()
        session = tf.Session()
        tb_writer = tf.summary.FileWriter(tensorboard_log_dir, session.graph)
        log_file = open(training_log_dir, 'w')
        global_step = 0
        self.print_and_log('model training...', log_file)

        session.run(tf.global_variables_initializer())
        for epoch in range(self.num_epoches):
            epoch_start_time = time.time()
            batch_step = 0
            loss_per_epoch = 0.0
            n_accu_per_epoch = 0.0
            t_accu_per_epoch = 0.0

            subset_generator = self.get_subset_data()
            for data in subset_generator:
                batch_generator = self.get_batch(data)
                for b_nt_x, b_nt_y, b_t_x, b_t_y in batch_generator:
                    batch_step += 1
                    global_step += 1
                    feed = {self.t_input: b_t_x,
                            self.n_input:b_nt_x,
                            self.n_target:b_nt_y,
                            self.t_target:b_t_y,
                            self.keep_prob:0.5}
                    batch_start_time = time.time()
                    show_loss, show_n_accu, show_t_accu, _, summary_str = session.run(
                        [self.loss, self.n_accu, self.t_accu, self.optimizer, self.merged_op],feed_dict=feed)
                    if self.is_log:
                        tb_writer.add_summary(summary_str, global_step)
                        tb_writer.flush()
                    loss_per_epoch += show_loss
                    n_accu_per_epoch += show_n_accu
                    t_accu_per_epoch += show_t_accu
                    batch_end_time = time.time()

                    if global_step % show_every_n == 0:
                        log_info = 'epoch:{}/{}  '.format(epoch+1, self.num_epoches) + \
                              'global_step:{}  '.format(global_step) + \
                              'loss:{:.2f}  '.format(show_loss) + \
                              'nt_accu:{:.2f}%  '.format(show_n_accu*100) + \
                              'tt_accu:{:.2f}%  '.format(show_t_accu*100) + \
                              'time cost per batch: {:.2f}/s'.format(batch_end_time - batch_start_time)
                        self.print_and_log(log_info, log_file)

                    if global_step % save_every_n == 0:
                        saver.save(session, model_save_dir + 'e{}_b{}.ckpt'.format(epoch, batch_step))
            epoch_end_time = time.time()
            epoch_cost_time = epoch_end_time - epoch_start_time
            epoch_log = 'EPOCH:{}/{}  '.format(epoch+1, self.num_epoches) + \
                        'time cost this epoch: {}/s'.format(epoch_cost_time) + \
                        'epoch average loss: {:.2f}  '.format(loss_per_epoch / batch_step) + \
                        'epoch average nt_accu:{:.2f}  '.format(n_accu_per_epoch / batch_step) + \
                        'epoch average tt_accu:{:.2f}  \n'.format(t_accu_per_epoch / batch_step)
            self.print_and_log(epoch_log, log_file)

        saver.save(session, model_save_dir + 'lastest_model.ckpt')
        self.print_and_log('model training finished...', log_file)
        session.close()
        log_file.close()


    def print_and_log(self, info, file):
        file.write(info)
        file.write('\n')
        print(info)






if __name__ == '__main__':
    terminalToken2int, terminalInt2token, nonTerminalToken2int, nonTerminalInt2token = utils.load_dict_parameter()
    num_ntoken = len(nonTerminalInt2token)
    num_ttoken = len(terminalInt2token)
    model = LSTM_Model(num_ntoken, num_ttoken)
 #   model.train()


