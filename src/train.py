from __future__ import division, print_function, absolute_import
import os, time, argparse, logging, traceback

import matplotlib

matplotlib.use('Agg')
from matplotlib import pyplot as plt
from exp_context import ExperimentContext

# Setting up Argument parser

parser = argparse.ArgumentParser()

parser.add_argument('-g', '--gpu', default=0, help='index of the gpu to be used. default: 0')
parser.add_argument('-r', '--resume', nargs='?', const=True, default=False,
                    help='if present, the training resumes from the latest step, '
                         'for custom step number, provide it as argument value')
parser.add_argument('-d', '--delete', nargs='+', default=[], choices=['logs', 'weights', 'results', 'all'],
                    help='delete the entities')
parser.add_argument('-w', '--weights', nargs='?', default='iter', choices=['iter', 'best_gen', 'best_pred'],
                    help='weight type to load if resume flag is provided. default: iter')
parser.add_argument('-hp', '--hyperparams', required=True, help='hyperparam class to use from HyperparamFactory')
parser.add_argument('-en', '--exp_name', default=None, help='experiment name. if not provided, it is taken from Hyperparams')

args = parser.parse_args()

ExperimentContext.set_context(args.hyperparams, args.exp_name)

logger = logging.getLogger(__name__)
LOG_FORMAT = "[{}: %(filename)s: %(lineno)3s] %(levelname)s: %(funcName)s(): %(message)s".format(ExperimentContext.exp_name)
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

import paths
from utils import viz_utils
from utils import bash_utils, model_utils
from dataloaders.factory import DataLoaderFactory

gpu_idx = str(args.gpu)

os.environ['CUDA_VISIBLE_DEVICES'] = gpu_idx

resume_flag = args.resume is not False

if 'all' in args.delete or 'logs' in args.delete or resume_flag is False:
    logger.warning('Deleting Logs...')
    bash_utils.delete_recursive(paths.logs_base_dir)
    print('')

if 'all' in args.delete or 'results' in args.delete:
    logger.warning('Deleting all results in {}...'.format(paths.results_base_dir))
    bash_utils.delete_recursive(paths.results_base_dir)
    print('')

model_utils.setup_dirs()

Model = ExperimentContext.get_model_class()
H = ExperimentContext.get_hyperparams()
print('input_size:', H.input_size, 'latent_size:', H.z_size)
dl = DataLoaderFactory.get_dataloader(H.dataloader, H.input_size, H.z_size)

model = Model('growing-gans')
model.build()
model.initiate_service()

print('Model service initiated...')

if resume_flag is not False:
    try:
        if args.resume is True:
            iter_no = model.load_params(dir_name='all', param_group='all')
        else:
            iter_no = int(args.resume)
            iter_no = model.load_params(dir_name='all', param_group='all', iter_no=iter_no)

        logger.info('Loading network weights from all-%d' % iter_no)
    except Exception as ex:
        traceback.print_exc()
        logger.error(ex)
        logger.error('Some Problem Occured while resuming... starting from iteration 1')
        raise Exception('Not found...')
else:
    iter_no = 0

if 'all' in args.delete or 'weights' in args.delete:
    logger.warning('Deleting all weights in {}...'.format(paths.all_weights_dir))
    bash_utils.delete_recursive(paths.all_weights_dir)
    model_utils.setup_dirs()
    print('')

x_train, x_test = dl.get_data()
print('Train Test Data loaded...')

max_epochs = 100000

n_step_console_log = 500
n_step_tboard_log = 10
n_step_validation = 50
n_step_iter_save = 5000
n_step_visualize = 1000
n_step_generator = 10
n_step_generator_decay = 0

en_loss_history = []
de_loss_history = []
di_loss_history = []
d_acc_history = []
g_acc_history = []
gen_loss_history = []

while iter_no < max_epochs:
    iter_no += 1

    iter_time_start = time.time()

    z_train = dl.get_z_dist(x_train.shape[0], dist_type=H.z_dist_type)
    z_test = dl.get_z_dist(x_test.shape[0], dist_type=H.z_dist_type)

    train_inputs = x_train, z_train
    test_inputs = x_test, z_test

    model.step_train_autoencoder(train_inputs)

    if (iter_no % n_step_generator) == 0:
        if H.train_generator_adv:
            model.step_train_adv_generator(train_inputs)
    else:
        model.step_train_discriminator(train_inputs)

    if (n_step_generator_decay > 0 and iter_no % n_step_generator_decay) == 0:
        n_step_generator = max(n_step_generator - 1, 1)

    train_losses = model.compute_losses(train_inputs, model.network_loss_variables)
    #
    if iter_no % n_step_console_log == 0:
        print('Step %i: Encoder Loss: %f' % (iter_no, train_losses[0]))
        print('Step %i: Disc Acc: %f' % (iter_no, train_losses[1]))
        print('Step %i: Gen  Acc: %f' % (iter_no, train_losses[2]))
        print('Step %i: x_recon Loss: %f' % (iter_no, train_losses[3]))
        print('Step %i: z_recon Loss: %f' % (iter_no, train_losses[4]))
        print()

    if iter_no % n_step_tboard_log == 0:
        model.get_logger('train').add_summary(train_losses[-1], iter_no)

    if iter_no % n_step_validation == 0:
        test_losses = model.compute_losses(test_inputs, model.network_loss_variables)
        model.get_logger('test').add_summary(test_losses[-1], iter_no)

    if iter_no % n_step_iter_save == 0:
        model.save_params(iter_no=iter_no)

    if H.show_visual_while_training and (iter_no % n_step_visualize == 0 or (iter_no < n_step_visualize and iter_no % 200 == 0)):
        def get_x_plots_data(x_input):
            _, x_real_true, x_real_false = model.discriminate(x_input)

            z_real_true = model.encode(x_real_true)
            z_real_false = model.encode(x_real_false)

            x_recon = model.reconstruct_x(x_input)
            _, x_recon_true, x_recon_false = model.discriminate(x_recon)

            z_recon_true = model.encode(x_recon_true)
            z_recon_false = model.encode(x_recon_false)

            return [
                (x_real_true, x_real_false),
                (z_real_true, z_real_false),
                (x_recon_true, x_recon_false),
                (z_recon_true, z_recon_false)
            ]


        def get_z_plots_data(z_input):
            x_input = model.decode(z_input)
            x_plots = get_x_plots_data(x_input)
            return [z_input] + x_plots[:-1]


        x_full = dl.get_full_space()

        x_plots_row1 = get_x_plots_data(x_test)
        z_plots_row2 = get_z_plots_data(z_test)
        x_plots_row3 = get_x_plots_data(x_full)
        plots_data = (x_plots_row1, z_plots_row2, x_plots_row3)
        figure = viz_utils.get_figure(plots_data)
        figure_name = 'plots-iter-%d.png' % iter_no
        figure_path = paths.get_result_path(figure_name)
        figure.savefig(figure_path)
        plt.close(figure)
        img = plt.imread(figure_path)
        model.log_image('test', img, iter_no)

    iter_time_end = time.time()

    if iter_no % n_step_console_log == 0:
        print('Single Iter Time: %.4f' % (iter_time_end - iter_time_start))
