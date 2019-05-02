import tensorflow as tf
import os
import sys

from data_generator import DataGenerator
from setting import Setting


"""Node2Vec for non-terminal node模型的定义和训练"""

sys.path.append('..')
RENAME_FLAG = False
nt_n_dim = 5 # 在模型中会对该值乘2，表示parent nt context 和 child nt context
nt_t_dim = 10 # non-terminal的前六个terminal child node

embed_setting = Setting()
show_every_n = embed_setting.show_every_n * 10
save_every_n = embed_setting.save_every_n
num_nt_token = embed_setting.num_non_terminal
num_tt_token = embed_setting.num_terminal

if RENAME_FLAG:
    model_save_dir = '../trained_model/rename_nt_node2vec/'
    tensorboard_log_dir = '../log_info/tensorboard_log/rename_nt_node2vec/'
else:
    model_save_dir = '../trained_model/node2vec/'
    tensorboard_log_dir = '../log_info/tensorboard_log/node2vec/'

training_log_dir = embed_setting.node2vec_train_log_dir


class NodeToVec_NT(object):

    def __init__(self, num_ntoken, num_ttoken,
                 embed_dim=300,
                 learning_rate=0.001,
                 n_sampled=100,
                 num_epochs=8,
                 time_steps=80,
                 batch_size = 80,
                 alpha = 0.7,
                 nt_n_dim = nt_n_dim,
                 nt_t_dim = nt_t_dim,):
        self.num_ntoken = num_ntoken
        self.num_ttoken = num_ttoken
        self.embed_dim = embed_dim
        self.learning_rate = learning_rate
        self.n_sampled = n_sampled
        self.num_epochs = num_epochs
        self.time_steps = time_steps
        self.batch_size = batch_size
        self.alpha = alpha

        self.nt_n_dim = nt_n_dim
        self.nt_t_dim = nt_t_dim


        self.build_model()

    def build_input(self):
        input_token = tf.placeholder(tf.int32, [None], name='input_x')
        nt_target = tf.placeholder(tf.int32, [None, None], name='nt_target')
        tt_target = tf.placeholder(tf.int32, [None, None], name='tt_target')
        return input_token, nt_target, tt_target

    def build_embedding(self, input_token):
        with tf.name_scope('embedding_matrix'):
            embedding_matrix = tf.Variable(
                tf.truncated_normal([self.num_ntoken, self.embed_dim]), dtype=tf.float32)
            embedding_rep = tf.nn.embedding_lookup(embedding_matrix, input_token)
        return embedding_rep

    def build_nt_output(self, input_):
        nt_weight = tf.get_variable('nt_weight', [self.embed_dim, self.num_ntoken],
                                    dtype=tf.float32, initializer=tf.truncated_normal_initializer)
        nt_bias = tf.get_variable('nt_bias', [self.num_ntoken], dtype=tf.float32,
                                  initializer=tf.truncated_normal_initializer)
        output = tf.matmul(input_, nt_weight) + nt_bias
        return output

    def bulid_onehot_nt_target(self, nt_target):
        onehot_n_target = tf.one_hot(nt_target, self.num_ntoken)
        n_shape = (self.batch_size * self.time_steps, self.num_ntoken)
        onehot_n_target = tf.reshape(onehot_n_target, n_shape)
        #onehot_t_target = tf.one_hot(t_target, self.num_ttoken)
        #onehot_t_target = tf.reshape(onehot_t_target, t_shape)
        return onehot_n_target #, onehot_t_target


    def build_nt_loss(self, embed_input, targets):
        nt_weight = tf.get_variable('nt_weight', [self.num_ntoken, self.embed_dim],
                                    dtype=tf.float32, initializer=tf.truncated_normal_initializer)
        nt_bias = tf.get_variable('nt_bias', [self.num_ntoken], dtype=tf.float32,
                                  initializer=tf.truncated_normal_initializer)
        loss = tf.nn.sampled_softmax_loss(nt_weight, nt_bias, targets, embed_input, self.num_ntoken,
                                          self.num_ntoken, num_true=self.nt_n_dim*2)
        loss = tf.reduce_mean(loss)
        return loss

    def build_tt_loss(self, embed_input, target):
        tt_weight = tf.get_variable('tt_weight', [self.num_ttoken, self.embed_dim],
                                    dtype=tf.float32, initializer=tf.truncated_normal_initializer)
        tt_bias = tf.get_variable('tt_bias', [self.num_ttoken], dtype=tf.float32,
                                  initializer=tf.truncated_normal_initializer)
        loss = tf.nn.sampled_softmax_loss(tt_weight, tt_bias, target, embed_input, self.n_sampled,
                                          self.num_ttoken, num_true=self.nt_t_dim)
        loss = tf.reduce_mean(loss)
        return loss

    def build_loss(self, nt_loss, tt_loss):
        nt_loss = self.alpha * nt_loss
        tt_loss = (1 - self.alpha) * tt_loss
        loss = tf.add(nt_loss, tt_loss)
        return loss

    def build_optimizer(self, loss):
        optimizer = tf.train.AdamOptimizer(self.learning_rate).minimize(loss)
        return optimizer

    def build_model(self):
        tf.reset_default_graph()
        self.input_token, self.nt_target, self.tt_target = self.build_input()
        self.embed_inputs = self.build_embedding(self.input_token)
        #nt_logits = self.build_nt_output(self.embed_inputs)
        #self.nt_loss = self.build_nt_loss(nt_logits, self.nt_target)
        self.nt_loss = self.build_nt_loss(self.embed_inputs, self.nt_target)
        self.tt_loss = self.build_tt_loss(self.embed_inputs, self.tt_target)
        self.loss = self.build_loss(self.nt_loss, self.tt_loss)
        self.optimizer = self.build_optimizer(self.loss)

        tf.summary.scalar('loss', self.loss)
        tf.summary.scalar('n_loss', self.nt_loss)
        tf.summary.scalar('t_loss', self.tt_loss)
        self.merged_op = tf.summary.merge_all()

    def train(self):
        model_name = "Node2Vec for non-terminal node has been initialized (renaming identifier: {})".format(RENAME_FLAG)
        self.print_and_log(model_name)
        
        global_step = 0
        saver = tf.train.Saver(max_to_keep=self.num_epochs + 1)

        session = tf.Session()
        session.run(tf.global_variables_initializer())
        tb_writer = tf.summary.FileWriter(tensorboard_log_dir, session.graph)
        generator = DataGenerator()
        for epoch in range(1, self.num_epochs+1):
            data_gen = generator.get_embedding_sub_data(cate='nt', is_rename=RENAME_FLAG)
            for index, sub_data in data_gen:
                batch_generator = generator.get_embedding_batch(sub_data)
                for batch_nt_x, batch_nt_y, batch_tt_y in batch_generator:
                    global_step += 1
                    feed = {
                        self.input_token:batch_nt_x,
                        self.nt_target:batch_nt_y,
                        self.tt_target:batch_tt_y,
                    }
                    n_loss, t_loss, loss, _, summary_str = session.run([
                        self.nt_loss, self.tt_loss, self.loss, self.optimizer, self.merged_op], feed_dict=feed)

                    tb_writer.add_summary(summary_str, global_step)
                    tb_writer.flush()

                    if global_step % show_every_n == 0:
                        log_info = 'epoch:{}/{}  '.format(epoch, self.num_epochs) + \
                                   'global_step:{}  '.format(global_step) + \
                                   'loss:{:.2f}(n_loss:{:.2f} + t_loss:{:.2f})  '.format(loss, n_loss, t_loss)
                        self.print_and_log(log_info)


            print('epoch{} model saved...'.format(epoch))
            saver.save(session, model_save_dir + 'EPOCH{}.ckpt'.format(epoch))

        session.close()


    def print_and_log(self, info):
        if not os.path.exists(training_log_dir):
            self.log_file = open(training_log_dir, 'w')
        self.log_file.write(info)
        self.log_file.write('\n')
        print(info)

    def get_most_similar(self, input_token):
        input_embedding = self.build_embedding(input_token)

    def get_represent_vector(self, input_token):
        repre_vector = self.build_embedding(input_token)
        return repre_vector.eval()






if __name__ == '__main__':
    model = NodeToVec_NT(num_nt_token, num_tt_token)
    model.train()