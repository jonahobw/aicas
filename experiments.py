"""
Run experiments that train, prune and finetune or quantize, and attack a DNN.
"""

# pylint: disable=import-error, too-many-instance-attributes, too-many-arguments
# pylint: disable=too-many-locals, logging-fstring-interpolation, invalid-name
# pylint: disable=unspecified-encoding

import json
from pathlib import Path
import os
import logging
from typing import Callable

import numpy as np
from shrinkbench.experiment import TrainingExperiment, PruningExperiment, AttackExperiment
from nets import get_hyperparameters, best_model

logger = logging.getLogger("Experiment")


class Experiment:
    """
    Creates a DNN, trains it on CIFAR10, then prunes and finetunes or quantizes, and attacks it.
    """

    def __init__(
        self,
        experiment_number: int,
        dataset: str,
        model_type: str,
        model_path: str = None,
        best_model_metric: str = None,
        quantization: int = None,
        prune_method: str = None,
        prune_compression: int = None,
        finetune_epochs: int = None,
        attack_method: str = None,
        attack_kwargs: dict = None,
        email: Callable = None,
        email_verbose: bool=False,
        gpu: int = None,
        debug: int = False,
        save_one_checkpoint: bool=False,
        seed: int = 42,
    ):

        """
        Initialize all class variables.

        :param experiment_number: the overall number of the experiment.
        :param dataset: dataset to train on.
        :param model_type: architecture of model.
        :param model_path: optionally provide a path to a pretrained model.  If specified,
            the training will be skipped as the model is already trained.
        :param best_model_metric: metric to use to determine which is the best model.  If none, the weights
            from the last epoch of training/finetuning will be used.
        :param quantization: the modulus for quantization.
        :param prune_method: the strategy for the pruning algorithm.
        :param prune_compression: the desired ratio of parameters in original to pruned model.
        :param finetune_epochs: number of training epochs after pruning/quantization.
        :param attack_method: the method for generating adversarial inputs.
        :param attack_kwargs: arguments to be passed to the attack function.
        :param email: callback function which has a signature of (subject, message).
        :param email_verbose: if true, sends an email at start and end of whole experiment, and end of
            training, pruning, fine-tuning, quantization, and attack.  If false, then only sends an
            email at the start and end of each experiment.
        :param gpu: the number of the gpu to run on.
        :param debug: whether or not to run in debug mode.  If specified, then
            should be an integer representing how many batches to run, and will only run 1
            epoch for training/validation/fine-tuning, so the experimental results with
            this option specified are not valid.
        :param save_one_checkpoint: if true, removes all previous checkpoints and only keeps this one.
            Since each checkpoint may be hundreds of MB, this saves lots of memory.
        :param seed: seed for random number generator.
        """

        self.paths, self.name = check_folder_structure(
            experiment_number,
            dataset,
            model_type,
            quantization,
            prune_method,
            attack_method,
            finetune_epochs,
            prune_compression,
        )
        self.experiment_number = experiment_number
        self.dataset = dataset
        self.model_type = model_type
        self.model_path = model_path

        # a model path may be provided to a pretrained model
        self.train_from_scratch = not bool(self.model_path)

        # the hyperparameters for training/fine-tuning and pruning are dependent on the
        # model architecture
        self.train_kwargs, self.prune_kwargs = get_hyperparameters(
            model_type, debug=debug
        )
        self.best_model_metric = best_model_metric
        self.quantization = quantization
        self.prune_method = prune_method
        self.prune_compression = prune_compression
        self.finetune_epochs = finetune_epochs
        self.attack_method = attack_method
        self.attack_kwargs = attack_kwargs
        self.save_one_checkpoint = save_one_checkpoint

        # there are 2 GPUs (may be changed for different hardware configurations)
        self.gpu = gpu
        if self.gpu is not None:
            self.train_kwargs["gpu"] = gpu
            self.prune_kwargs["gpu"] = gpu

        self.debug = debug
        if debug:
            logger.warning(
                f"Debug is {debug}.  Results will not be valid with this setting on."
            )
        # if no email is provided, set up a dummy function that does nothing.
        self.email = email if email is not None else lambda x, y: 0
        self.email_verbose = email_verbose
        self.seed = seed
        self.params = self.save_variables()
        self.train_exp = None
        self.prune_exp = None
        self.attack_exp = None

    def save_variables(self) -> None:
        """Save experiment parameters to a file in this experiment's folder"""

        params_path = self.paths["model"] / "experiment_params.json"
        variables = ["name", "experiment_number", "dataset", "model_type", "model_path",
                     "best_model_metric", "quantization", "prune_method", "prune_compression",
                     "finetune_epochs", "attack_method", "attack_kwargs", "email_verbose",
                     "gpu", "debug", "save_one_checkpoint", "seed", "train_from_scratch",
                     "train_kwargs", "prune_kwargs"]
        params = {x: getattr(self, x) for x in variables}
        default = lambda x: "json encode error"
        params = json.dumps(params, skipkeys=True, indent=4, default=default)
        # params["train_kwargs"] = json.dumps(self.train_kwargs, skipkeys=True, indent=4, default=default)
        # params["prune_kwargs"] = json.dumps(self.prune_kwargs, skipkeys=True, indent=4, default=default)
        with open(params_path, "w") as file:
            file.write(params)
        return params

    def run(self) -> None:
        """Train, prune and finetune or quantize, and attack a DNN."""

        self.email(f"Experiment started for {self.name}", self.params)

        attacked = False

        if self.train_from_scratch:
            self.train()
            # if attack is specified, only run after initial training if we aren't pruning/quantizing.
            if self.attack_method is not None and not self.prune_method and not self.quantization:
                self.attack()
                attacked = True
        if self.prune_method:
            self.prune()
        if self.quantization:
            self.quantize()
        # if we are pruning/quantizing, attack runs here when we have the final model we want to attack.
        if self.attack_method is not None and not attacked:
            self.attack()

        self.email(f"Experiment ended for {self.name}", self.params)

    def train(self) -> None:
        """Train a CNN from scratch."""

        assert self.model_path is None, (
            "Training is done from scratch, should not be providing a pretrained model"
            "to train again."
        )
        self.train_exp = TrainingExperiment(
            dataset=self.dataset,
            model=self.model_type,
            path=self.paths["model"],
            checkpoint_metric=self.best_model_metric,
            debug=self.debug,
            save_one_checkpoint = self.save_one_checkpoint,
            seed = self.seed,
            **self.train_kwargs,
        )
        self.train_exp.run()

        # set the model path to be the path to the best model from training.
        self.model_path = best_model(self.train_exp.path, metric=self.best_model_metric)

        if self.email_verbose:
            self.email(f"Training for {self.name} completed.", "")

    def prune(self) -> None:
        """
        Prunes a CNN.

        Can either prune an existing CNN from a different experiment (when model_path
        is provided as a class parameter) or can prune a model that was also trained during
        this experiment (model_path not provided).
        :return: None
        """

        assert self.model_path is not None, (
            "Either a path to a trained model must be provided or training parameters must be "
            "provided to train a model from scratch."
        )
        logger.info(f"Pruning the model saved at {self.model_path}")

        self.prune_kwargs["train_kwargs"]["epochs"] = self.finetune_epochs

        self.prune_exp = PruningExperiment(
            dataset=self.dataset,
            model=self.model_type,
            strategy=self.prune_method,
            compression=self.prune_compression,
            checkpoint_metric=self.best_model_metric,
            resume=str(self.model_path),
            path=str(self.paths["model"]),
            debug=self.debug,
            save_one_checkpoint=self.save_one_checkpoint,
            seed=self.seed,
            **self.prune_kwargs,
        )
        self.prune_exp.run()

        if self.email_verbose:
            self.email(f"Pruning for {self.name} completed.", "")

    def quantize(self):
        """Quantize a DNN."""

    def attack(self):
        """Attack a DNN."""

        default_pgd_args = {"eps": 2 / 255, "eps_iter": 0.001, "nb_iter": 5, "norm": np.inf}

        train = self.attack_kwargs.pop('train')
        default_pgd_args.update(**self.attack_kwargs)

        assert self.model_path is not None, (
            "Either a path to a trained model must be provided or training parameters must be "
            "provided to train a model from scratch."
        )

        self.attack_exp = AttackExperiment(
            model_path=self.model_path,
            model_type=self.model_type,
            dataset=self.dataset,
            dl_kwargs=self.train_kwargs['dl_kwargs'],
            train=train,
            attack=self.attack_method,
            attack_params=default_pgd_args,
            path=self.paths["model"],
            gpu=self.gpu,
            seed=self.seed,
            debug=self.debug,
        )
        self.attack_exp.run()

        if self.email_verbose:
            self.email(
                f"{self.attack_method} attack on {self.model_type} Concluded.",
                json.dumps(self.attack_exp.save_variables(), indent=4)
            )


def check_folder_structure(
    experiment_number: int,
    dataset: str,
    model_type: str,
    quantize: int,
    prune: str,
    attack: str,
    finetune_epochs: int,
    compression: int,
) -> (str, dict):
    """
    Setup the paths to the dataset and experiment folders to follow the folder schema.
    For the folder schema, an experiment is defined on 2 levels: on one level, an
    experiment is defined by a model architecture, and pruning method, # of fine-tuning
    iterations, and compression ratio or quanization modulus, and experiments can be run
    for all combinations of the enumerated parameters.  On a high level, an experiment is
    defined as 1 run of all the experiments on the lower level.  Having multiple of the
    higher experiments means having duplicate runs of all model architecture,
    pruning method, # of fine-tuning iterations, and compression ratio or quanization
    modulus combinations.

    The folder schema is described below.

    aicas/
        datasets/
            CIFAR10/
        experiments/
            # high level experiment folders
            experiment1/
                VGG/
                    cifar10/
                    # low level experiment folders
                        vgg_<pruning_method>_<compression>_<finetuning_iterations>/
                            shrinkbench folder generated for training/
                            shrinkbench folder generated for pruning/
                                attacks/
                                    <attack_method>/
                                        images/
                                        train_attack_results-*.json
                            experiment_params.json
                        ...
                ResNet20/
                GoogLeNet/
                MobileNet/
            experiment2/
                ...

    :param experiment_number: the overall number of the experiment.
    :param dataset: dataset to train on.
    :param model_type: architecture of model.
    :param quantize: the modulus for quantization.
    :param prune_method: the strategy for the pruning algorithm.
    :param attack: the method for generating adversarial inputs.
    :param finetune_epochs: number of training epochs after pruning/quantization.
    :param compression: the desired ratio of parameters in original to pruned model.

    :return: a tuple (dict, str).  The string is the name of the model folder.
        The dictionary has keys which are the names of paths and the values are
        pathlib.Path object.  The keys are:
        'root': the root directory of the repository
        'datasets': path to the datasets folder
        'experiments': path to the folder of all experiments.
        'experiment': path to the folder of the experiment of which this experiment
            is a part of.
        'dataset': path to the folder storing the dataset that the DNN will be trained on.
        'model_type': path to the subfolder of the experiment folder for this model architecture
        'model_dataset' path to the subfolder of the 'model_type' folder for this dataset
        'model': the folder in which all data of this experiment will be saved.
    """

    root = Path.cwd()

    path_dict = {
        "root": root,
        "datasets": root / "datasets",
        "experiments": root / "experiments",
        "experiment": root / "experiments" / f"experiment_{experiment_number}",
    }
    path_dict["dataset"] = path_dict["datasets"] / dataset
    path_dict["model_type"] = path_dict["experiment"] / model_type
    path_dict["model_dataset"] = path_dict["model_type"] / dataset

    # model folder name must be unique for each variation of
    #   pruning/quantizing/finetuning for a certain model architecture
    model_folder_name = f"{model_type.lower()}"

    if quantize:
        path_dict["model"] = (
            path_dict["model_dataset"] / f"{model_type.lower()}_{quantize}_quantization"
        )
    elif prune:
        model_folder_name += f"_{prune}_{compression}_compression"
        assert (
            finetune_epochs > 0
        ), "Number of finetuning epochs must be provided when pruning"
    if finetune_epochs:
        model_folder_name += f"_{finetune_epochs}_finetune_iterations"
        path_dict["model"] = path_dict["model_dataset"] / model_folder_name
    else:
        path_dict["model"] = path_dict["model_dataset"] / model_type.lower()

    # see if experiment has been run already:
    if path_dict["model"].exists():
        logger.warning(f"Path {path_dict['model']} already exists.")

    if attack and "model" in path_dict:
        path_dict["attacks"] = path_dict["model"] / "attacks"
        path_dict["attack"] = path_dict["attacks"] / attack

    for folder_name in path_dict.keys():
        if not path_dict[folder_name].exists():
            path_dict[folder_name].mkdir(parents=True, exist_ok=True)

    # set environment variable to be used by shrinkbench
    os.environ["DATAPATH"] = str(path_dict["datasets"])

    return path_dict, model_folder_name


if __name__ == "__main__":
    for architecture in ["VGG", "GoogLeNet", "MobileNetV2", "ResNet18"]:
        a = Experiment(0, "CIFAR10", architecture, prune_method="full")
