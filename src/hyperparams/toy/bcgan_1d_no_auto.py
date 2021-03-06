import tensorflow as tf
from hyperparams import base


class Hyperparams(base.Hyperparams):
    dtype = tf.float32

    input_size = 1

    z_size = 1

    lr_autoencoder = 0.0005
    lr_decoder = 0.0005
    lr_disc = 0.0005

    z_dist_type = 'normal'  # ['uniform', 'normal', 'sphere']

    show_visual_while_training = True

    train_generator_adv = True
    train_autoencoder = False

    model = 'bcgan'
    exp_name = 'bcgan_v1_1D_1D_two_gaussians_no_autoencoder'
