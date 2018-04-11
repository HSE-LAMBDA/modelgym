from modelgym.trainers.trainer import Trainer
from modelgym.utils.model_space import process_model_spaces
from modelgym.utils.evaluation import crossval_fit_eval

from hyperopt import fmin, Trials, STATUS_OK, tpe, rand
import numpy as np


class HyperoptTrainer(Trainer):
    """HyperoptTrainer is a class for models hyperparameter optimization, based on hyperopt library"""

    def __init__(self, model_spaces, algo=None, trials=None):
        """
        Args:
            model_spaces (list of modelgym.models.Model or modelgym.utils.ModelSpaces): list of model spaces
                (model classes and parameter spaces to look in). If some list item is Model, it is
                converted in ModelSpace with default space and name equal to model class __name__
            algo (function, e.g `hyperopt.rand.suggest` or `hyperopt.tpe.suggest`): algorithm to use for optimization
            tracker (modelgym.trackers.Tracker, optional): tracker to save
                (and load, if there was any) optimization progress.
        Raises:
            ValueError if there are several model_spaces with similar names
        """

        super().__init__(model_spaces, trials)
        self.model_spaces = process_model_spaces(model_spaces)
        self.trials = trials
        self.algo = algo

    # TODO: consider different batch_size for different models
    def crossval_optimize_params(self, opt_metric, dataset, opt_evals,
                                 cv=3, metrics=None,
                                 verbose=False, batch_size=10,
                                 client=None,
                                 **kwargs):
        """Find optimal hyperparameters for all models

        Args:
            opt_metric (modelgym.metrics.Metric): metric to optimize
            dataset (modelgym.utils.XYCDataset or None): dataset
            cv (int or list of tuples of (XYCDataset, XYCDataset)): if int, then number of cross-validation folds or
                cross-validation folds themselves otherwise.
            opt_evals (int): number of cross-validation evaluations
            metrics (list of modelgym.metrics.Metric, optional): additional metrics to evaluate
            verbose (bool): Enable verbose output.
            batch_size (int): periodicity of saving results to tracker
            client:
            **kwargs: ignored

        Note:
            if cv is int, than dataset is split into cv parts for cross validation. Otherwise, cv folds are used.
        """

        if metrics is None:
            metrics = []

        if self.trials is None:
            self.trials = {name: Trials() for name in self.model_spaces}
        else:
            mongo_uri = self.trials
            self.trials = {name: MongoTrials(mongo_uri, exp_key=name) for name in self.model_spaces }

        metrics.append(opt_metric)

        if isinstance(cv, int) and client is None:
            cv = dataset.cv_split(cv)

        for name, model_space in self.model_spaces.items():

            """
            What is that for ?
            if len(state) == opt_evals:
                continue
            """
            if client is None:
                fn = lambda params: self._eval_fn(
                    model_type=model_space.model_class,
                    params=params,
                    cv=cv, metrics=metrics, verbose=verbose
                )
            else:
                fn = lambda params: client.eval(
                    model_type=model_space.model_class,
                    params=params,
                    data_path=dataset, cv=cv, metrics=metrics)

            fmin(fn=fn,
                 space=model_space.space,
                 algo=self.algo,
                 max_evals=opt_evals,
                 trials=self.trials[name])

    def get_best_results(self):
        """When training is complete, return best parameters (and additional information) for each model space

        Returns:
            dict of shape::

                {
                    name (str): {
                        "result": {
                            "loss": float,
                            "loss_variance": float,
                            "status": "ok",
                            "metric_cv_results": list,
                            "params": dict
                        },
                        "model_space": modelgym.utils.ModelSpace
                    }
                }

            name is a name of corresponding model_space,

            metric_cv_results contains dict's from metric names to calculated metric values for each fold in cv_fold,

            params is optimal parameters of corresponding model

            model_space is corresponding model_space.
        """
        return {name: {"result": trials.best_trial["result"],
                       "model_space": self.model_spaces[name]}
                for (name, trials) in self.state.items()}

    @staticmethod
    def _eval_fn(model_type, params, cv, metrics, verbose):
        """Evaluates function to minimize with additional information to remember.
        Args:
            model_type (type, subclass of Model)
            params (dict of str:obj): model parameters
            cv (list of tuple like (XYCDataset, XYCDataset)): cross validation folds
            metrics (list of modelgym.metrics.Metric): metrics to evaluate.
                Last metric is considered to be either loss (if metric.is_min_optimal is True) or -loss.
                Loss is the metric we want to minimize.
            verbose (bool): Enable verbose output.
        Returns:
            dict of shape: {
                "loss": float,
                "loss_variance": float,
                "status": "ok",
                "metric_cv_results": list,
                "params": dict
            },
            metric_cv_results contains dict's from metric names to calculated metric values for each fold in cv_fold
            params is just a copy of input argument params
        """

        result = crossval_fit_eval(model_type, params, cv, metrics, verbose)
        result["status"] = STATUS_OK
        losses = [cv_result[metrics[-1].name]
                  for cv_result in result["metric_cv_results"]]
        result["loss_variance"] = np.std(losses)

        return result


class TpeTrainer(HyperoptTrainer):
    """TpeTrainer is a HyperoptTrainer using Tree-structured Parzen Estimator"""

    def __init__(self, model_spaces, trials=None):
        super().__init__(model_spaces, algo=tpe.suggest, trials=trials)


class RandomTrainer(HyperoptTrainer):
    """TpeTrainer is a HyperoptTrainer using Random search"""

    def __init__(self, model_spaces, trials=None):
        super().__init__(model_spaces, algo=rand.suggest, trials=trials)
