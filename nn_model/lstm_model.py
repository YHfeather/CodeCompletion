import tensorflow as tf
from setting import Setting

"""所有lstm模型的基类，即使用最原始的LSTM模型进行训练和预测"""

base_setting = Setting()

class RnnModel(object):
    """A basic LSTM model for code completion"""
    def __init__(self,
                 num_ntoken, num_ttoken, is_training=True, kernel='LSTM',
                 batch_size=50,
                 n_embed_dim=1500,
                 t_embed_dim=1500,
                 num_hidden_units=1500,
                 learning_rate=0.0025,
                 time_steps=50,
                 grad_clip=5,):
        self.n_embed_dim = n_embed_dim
        self.num_ntoken = num_ntoken
        self.num_ttoken = num_ttoken
        self.t_embed_dim = t_embed_dim
        self.num_hidden_units = num_hidden_units
        self.learning_rate = learning_rate
        self.grad_clip = grad_clip
        self.time_steps = time_steps
        self.batch_size = batch_size
        self.kernel = kernel

        if not is_training:
            self.batch_size = 1
            self.time_steps = 50

        self.build_model()

    def build_input(self):
        """create input and target placeholder"""
        n_input = tf.placeholder(tf.int32, [None, None], name='n_input')
        t_input = tf.placeholder(tf.int32, [None, None], name='t_input')
        n_target = tf.placeholder(tf.int32, [None, None], name='n_target')
        t_target = tf.placeholder(tf.int32, [None, None], name='t_target')
        keep_prob = tf.placeholder(tf.float32, name='keep_prob')
        return n_input, t_input, n_target, t_target, keep_prob

    def build_input_embed(self, n_input, t_input):
        """create input embedding matrix and return embedding vector"""
        n_embed_matrix = tf.Variable(tf.random_uniform(
            [self.num_ntoken, self.n_embed_dim], minval=-0.05, maxval=0.05),  name='n_embed_matrix')
        t_embed_matrix = tf.Variable(tf.random_uniform(
            [self.num_ttoken, self.t_embed_dim], minval=-0.05, maxval=0.05), name='t_embed_matrix')
        n_input_embedding = tf.nn.embedding_lookup(n_embed_matrix, n_input)
        t_input_embedding = tf.nn.embedding_lookup(t_embed_matrix, t_input)
        return n_input_embedding, t_input_embedding

    def build_lstm(self, keep_prob):
        """create lstm cell and init state"""
        def get_cell():
            if self.kernel == 'LSTM':
                cell = tf.contrib.rnn.BasicLSTMCell(self.num_hidden_units)
                print('LSTM is using...')
            elif self.kernel == 'GRU':  # GRU RNN
                cell = tf.contrib.rnn.GRUCell(self.num_hidden_units)
                print('GRU is using...')
            else:
                raise AttributeError
            cell = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=keep_prob)
            return cell
        lstm_cell = get_cell()
        init_state = lstm_cell.zero_state(self.batch_size, dtype=tf.float32)
        return lstm_cell, init_state

    def build_dynamic_rnn(self, cells, lstm_input, lstm_state):
        """using dynamic rnn to run LSTM automatically"""
        lstm_output, final_state = tf.nn.dynamic_rnn(cells, lstm_input, initial_state=lstm_state)
        # reshape lstm_output from [batch_size, time_steps, n_units] to [batch_size*time_steps, n_units]
        lstm_output = tf.reshape(lstm_output, [-1, self.num_hidden_units])

        return lstm_output, final_state

    def build_n_output(self, lstm_output):
        """using a trainable matrix to transform the output of lstm to non-terminal token prediction"""
        with tf.variable_scope('non_terminal_softmax'):
            nt_weight = tf.Variable(tf.random_uniform(
                [self.num_hidden_units, self.num_ntoken], minval=-0.05, maxval=0.05))
            nt_bias = tf.Variable(tf.zeros(self.num_ntoken))
        nt_logits = tf.matmul(lstm_output, nt_weight) + nt_bias
        return nt_logits

    def build_t_output(self, lstm_output):
        """using a trainable matrix to transform the otuput of lstm to terminal token prediction"""
        with tf.variable_scope('terminal_softmax'):
            t_weight = tf.Variable(tf.random_uniform(
                [self.num_hidden_units, self.num_ttoken], minval=-0.05, maxval=0.05))
            t_bias = tf.Variable(tf.zeros(self.num_ttoken))
        tt_logits = tf.matmul(lstm_output, t_weight) + t_bias
        return tt_logits

    def build_softmax(self, logits):
        softmax_output = tf.nn.softmax(logits=logits)
        return softmax_output

    def build_loss(self, n_loss, t_loss):
        """add n_loss, t_loss together"""
        loss = tf.add(n_loss, t_loss)
        return loss

    def build_nt_loss(self, n_logits, n_target):
        """calculate the loss function of non-terminal prediction"""
        n_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=n_logits, labels=n_target)
        n_loss = tf.reduce_mean(n_loss)
        return n_loss

    def build_tt_loss(self, t_logits, t_target):
        """calculate the loss function of terminal prediction"""
        t_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=t_logits, labels=t_target)
        t_loss = tf.reduce_mean(t_loss)
        return t_loss

    def build_accuracy(self, n_output, n_target, t_output, t_target, topk=3):
        """calculate the accuracy of non-terminal terminal top k prediction"""
        n_equal = tf.nn.in_top_k(n_output, n_target, k=topk)
        t_equal = tf.nn.in_top_k(t_output, t_target, k=topk)
        n_accu = tf.reduce_mean(tf.cast(n_equal, tf.float32))
        t_accu = tf.reduce_mean(tf.cast(t_equal, tf.float32))
        return n_accu, t_accu

    def build_topk_prediction(self, n_output, t_output, define_k=3):
        """return the top k prediction by model"""
        n_topk_possibility, n_topk_prediction = tf.nn.top_k(n_output, k=define_k)
        t_topk_possibility, t_topk_prediction = tf.nn.top_k(t_output, k=define_k)
        return n_topk_prediction, n_topk_possibility, t_topk_prediction, t_topk_possibility

    def build_optimizer(self, loss):
        """build optimizer for model, using learning rate decay and gradient clip"""
        self.decay_epoch = tf.Variable(0, trainable=False)
        decay_learning_rate = tf.train.exponential_decay(self.learning_rate, self.decay_epoch, 1, 0.9)
        optimizer = tf.train.AdamOptimizer(decay_learning_rate)
        gradient_pair = optimizer.compute_gradients(loss)
        clip_gradient_pair = []
        for grad, var in gradient_pair:
            grad = tf.clip_by_value(grad, -self.grad_clip, self.grad_clip)
            clip_gradient_pair.append((grad, var))
        optimizer = optimizer.apply_gradients(clip_gradient_pair)
        return optimizer, decay_learning_rate

    def build_onehot_target(self, n_target, t_target):
        """not used, transform int target to one-hot-encoding target"""
        onehot_n_target = tf.one_hot(n_target, self.num_ntoken)
        n_shape = (self.batch_size * self.time_steps, self.num_ntoken)
        t_shape = (self.batch_size * self.time_steps, self.num_ttoken)
        onehot_n_target = tf.reshape(onehot_n_target, n_shape)
        onehot_t_target = tf.one_hot(t_target, self.num_ttoken)
        onehot_t_target = tf.reshape(onehot_t_target, t_shape)
        return onehot_n_target, onehot_t_target

    def build_summary(self, summary_dict):
        """summary model info for tensorboard"""
        for key, value in summary_dict.items():
            tf.summary.scalar(key, value)
        merged_op = tf.summary.merge_all()
        return merged_op

    def build_model(self):
        """create model"""
#        tf.reset_default_graph()
        self.n_input, self.t_input, self.n_target, self.t_target, self.keep_prob = self.build_input()
        n_input_embedding, t_input_embedding = self.build_input_embed(
            self.n_input, self.t_input)
        lstm_input = tf.add(n_input_embedding, t_input_embedding)

        cells, self.init_state = self.build_lstm(self.keep_prob)
        self.lstm_state = self.init_state
        lstm_output, self.final_state = self.build_dynamic_rnn(cells, lstm_input, self.lstm_state)

        n_logits = self.build_n_output(lstm_output)
        t_logits = self.build_t_output(lstm_output)

        # loss calculate
        # n_target = tf.reshape(self.n_target, [self.batch_size*self.time_steps])
        # t_target = tf.reshape(self.t_target, [self.batch_size*self.time_steps])
        n_target = tf.reshape(self.n_target, [-1])
        t_target = tf.reshape(self.t_target, [-1])
        self.n_loss = self.build_nt_loss(n_logits, n_target)
        self.t_loss = self.build_tt_loss(t_logits, t_target)
        self.loss = self.build_loss(self.n_loss, self.t_loss)
        # optimizer
        self.optimizer, self.decay_learning_rate = self.build_optimizer(self.loss)

        # top one accuracy
        self.n_accu, self.t_accu = self.build_accuracy(n_logits, n_target, t_logits, t_target, topk=1)

        # top k accuracy
        self.n_topk_accu, self.t_topk_accu = self.build_accuracy(
            n_logits, n_target, t_logits, t_target, topk=3)

        # top k prediction with possibility
        self.n_output = self.build_softmax(n_logits)
        self.t_output = self.build_softmax(t_logits)
        self.n_topk_pred, self.n_topk_poss, self.t_topk_pred, self.t_topk_poss = \
            self.build_topk_prediction(self.n_output, self.t_output)

        summary_dict = {'train loss': self.loss,
                        'non-terminal loss': self.t_loss, 'terminal loss': self.t_loss,
                        'n_accuracy': self.n_accu, 't_accuracy': self.t_accu,
                        'top3_nt_accu':self.n_topk_accu, 'top3_tt_accu':self.t_topk_accu,
                        'learning_rate': self.decay_learning_rate}
        self.merged_op = self.build_summary(summary_dict)

        print('basic LSTM model has been created...')




if __name__ == '__main__':
    num_terminal = base_setting.num_terminal
    num_non_terminal = base_setting.num_non_terminal
    model = RnnModel(num_non_terminal, num_terminal, is_training=True, kernel='GRU')
