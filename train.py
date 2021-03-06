from datetime import datetime
from tensorflow.python.platform import gfile
import tensorflow as tf
from data_preprocessing import BatchGenerator
from DepthLoss import build_loss
from vgg16 import Vgg16Model
from Utills import output_predict,output_groundtruth

BATCH_SIZE = 16
TRAIN_FILE = "train.csv"
TEST_FILE = "test.csv"
EPOCHS = 2000

IMAGE_HEIGHT = 224
IMAGE_WIDTH = 224
TARGET_HEIGHT = 55
TARGET_WIDTH = 74

# decayed_learning_rate = learning_rate * decay_rate ^ (global_step / decay_steps)
INITIAL_LEARNING_RATE = 0.00001
LEARNING_RATE_DECAY_FACTOR = 0.9
MOVING_AVERAGE_DECAY = 0.999999
NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN = 500
NUM_EPOCHS_PER_DECAY = 30

Weights_DIR = 'Weights'
SCALE2_DIR = 'Scale2'

logs_path_train = './tmp/multi_scale/1/train'
logs_path_test = './tmp/multi_scale/1/test'

def train_model(continue_flag=False):

    if not gfile.Exists(Weights_DIR):
        gfile.MakeDirs(Weights_DIR)

    with tf.Graph().as_default():
        # get batch
        global_step = tf.Variable(0, name='global_step', trainable=False)
        with tf.device('/cpu:0'):
            batch_generator = BatchGenerator(batch_size=BATCH_SIZE)
            # train_images, train_depths, train_pixels_mask = batch_generator.csv_inputs(TRAIN_FILE)
            train_images, train_depths, train_pixels_mask,names = batch_generator.csv_inputs(TRAIN_FILE,batch_size=BATCH_SIZE)
            test_images, test_depths, test_pixels_mask, names = batch_generator.csv_inputs(TEST_FILE,batch_size=4)
        '''
        # placeholders
            training_images = tf.placeholder(tf.float32, shape=[None, IMAGE_HEIGHT, IMAGE_WIDTH, 3], name="training_images")
            depths = tf.placeholder(tf.float32, shape=[None, TARGET_HEIGHT, TARGET_WIDTH, 1], name="depths")
            pixels_mask = tf.placeholder(tf.float32, shape=[None, TARGET_HEIGHT, TARGET_WIDTH, 1], name="pixels_mask")
        '''

        # build model
        vgg = Vgg16Model()
        isTraining =  tf.placeholder(tf.bool)
        images = tf.placeholder(tf.float32, [None, 224,224,3])
        depths = tf.placeholder(tf.float32, [None, 24,24,1])
        pixels_masks = tf.placeholder(tf.float32, [None, 24,24,1])

        vgg.build(images,isTraining=isTraining)

        loss = build_loss(scale2_op=vgg.outputdepth, depths=depths, pixels_mask=pixels_masks)

        l2_loss = 0
        training_layers = ['conv_Pred', 'fc6', 'fc7', 'fc8']
        fine_tuing_layers = ['conv5_1','conv4_3', 'conv4_2','conv5_2','conv5_3']

        trainig_params = []
        tunning_params = []

        for W in tf.trainable_variables():
            if "batch_normalization" not in W.name:
                print(W.name)
                l2_loss += tf.nn.l2_loss(W)
            for layer in training_layers:
                if layer in W.name:
                    print('train')
                    trainig_params.append(W)
                    break
            for layer in fine_tuing_layers:
                if layer in W.name:
                    print('tune')
                    tunning_params.append(W)
                    break

        loss +=  1e-4 * l2_loss
        loss_summary = tf.summary.scalar("Loss", loss)


        tf.summary.scalar("cost", loss)
        #learning rate
        # num_batches_per_epoch = float(NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN) / BATCH_SIZE





        # decay_steps = int(num_batches_per_epoch * NUM_EPOCHS_PER_DECAY)
        lr_train = tf.train.exponential_decay(
            1e-5,
            global_step,
            5000,
            0.1,
            staircase=True)

        lr_tune = tf.train.exponential_decay(
            1e-5,
            global_step,
            5000,
            0.1,
            staircase=True)

        #optimizer
        optimizer_train = tf.train.AdamOptimizer(learning_rate=lr_train).minimize(loss, global_step=global_step,var_list=trainig_params)
        optimizer_tune = tf.train.AdamOptimizer(learning_rate=lr_tune).minimize(loss, global_step=global_step,var_list=tunning_params)
        optimizer = tf.group(optimizer_train,optimizer_tune)
        # TODO: define model saver

        # Training session
        # sess_config = tf.ConfigProto(log_device_placement=True)
        # sess_config.gpu_options.allocator_type = 'BFC'
        # sess_config.gpu_options.per_process_gpu_memory_fraction = 0.80

        '''
        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        '''

        # summary_op = tf.summary.merge_all()

        with tf.Session() as sess:

            writer_train = tf.summary.FileWriter(logs_path_train, graph=sess.graph)
            writer_test = tf.summary.FileWriter(logs_path_test, graph=sess.graph)

            sess.run(tf.global_variables_initializer())

            # Saver
            # dictionary to each scale to define to seprate collections

            learnable_params = tf.trainable_variables()
            not_saved_params = ['batch_normalization_3/gamma:0','batch_normalization_4/gamma:0','batch_normalization_5/gamma:0','batch_normalization_3/beta:0','batch_normalization_4/beta:0','batch_normalization_5/beta:0']

            saved_params = []
            for v in learnable_params:
                if 'batch_normalization' not in v.name:
                    saved_params.append(v)
            # add variables to it's corresponding dictionary

            # define savers
            saver_learnable = tf.train.Saver(learnable_params, max_to_keep=4)
            saver_saved = tf.train.Saver(saved_params, max_to_keep=4)
            # restore params if we need to continue on the previous training
            if continue_flag:
                weights_ckpt = tf.train.get_checkpoint_state(Weights_DIR)
                if weights_ckpt and weights_ckpt.model_checkpoint_path:
                    print("Weights Loading.")
                    saver_saved.restore(sess, weights_ckpt.model_checkpoint_path)
                    print("Weights Restored.")
                else:
                    print("No Params available")


            # initialize the queue threads to start to shovel data
            coord = tf.train.Coordinator()
            threads = tf.train.start_queue_runners(coord=coord)

            # p = tf.Print(data_file,[data_file],message=)

            for epoch in range(EPOCHS):
                for i in range(1000):

                    batch_images , ground_truth , batch_masks = sess.run([train_images,train_depths,train_pixels_mask])

                    _, loss_value, out_depth, train_summary = sess.run([optimizer, loss, vgg.outputdepth,loss_summary]
                                                                 ,feed_dict={images:batch_images , depths:ground_truth,pixels_masks:batch_masks,isTraining:True})
                    writer_train.add_summary(train_summary, epoch * 1000 + i)

                    if  i%10 ==0:
                        batch_images_test, ground_truth_test, batch_masks_test = sess.run([test_images, test_depths, test_pixels_mask])
                        validation_loss , test_summary = sess.run([loss,loss_summary],feed_dict={images:batch_images_test , depths:ground_truth_test,pixels_masks:batch_masks_test,isTraining:False})
                        writer_test.add_summary(test_summary, epoch * 1000 + i)


                    if i % 10 == 0:
                        # log.info('step' + loss_value)
                        print("%s: %d[epoch]: %d[iteration]: train loss %f : valid loss %f " % (datetime.now(), epoch, i, loss_value,validation_loss))

                    # print("%s: %d[epoch]: %d[iteration]: train loss %f" % (datetime.now(), epoch, i, loss_value))
                    if i % 500 == 0:
                        output_groundtruth(out_depth, ground_truth,"data/predictions/predict_scale1_%05d_%05d" % (epoch, i))
                weights_checkpoint_path = Weights_DIR + '/model'
                saver_learnable.save(sess, weights_checkpoint_path)
            # stop our queue threads and properly close the session
            coord.request_stop()
            coord.join(threads)
            sess.close()

def main(argv=None):
    train_model(True)

if __name__ == '__main__':
    tf.app.run()