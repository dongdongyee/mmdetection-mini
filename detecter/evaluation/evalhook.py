from cvcore import Hook
from cvcore.utils import dist_comm
from ..utils.misc import flatten_results_dict

__all__=['EvalHook']


class EvalHook(Hook):
    """
    Run an evaluation function periodically, and at the end of training.

    It is executed every ``eval_period`` iterations and after the last iteration.
    """

    def __init__(self, eval_function, by_epoch, eval_period):
        """
        Args:
            eval_period (int): the period to run `eval_function`. Set to 0 to
                not evaluate periodically (but still after the last iteration).
            eval_function (callable): a function which takes no arguments, and
                returns a nested dict of evaluation metrics.

        Note:
            This hook must be enabled in all or none workers.
            If you would like only certain workers to perform evaluation,
            give other workers a no-op function (`eval_function=lambda: None`).
        """
        self.by_epoch=by_epoch
        self._period = eval_period
        self._func = eval_function


    def _do_eval(self,runner):
        results = self._func()

        if results:
            assert isinstance(
                results, dict
            ), "Eval function must return a dict. Got {} instead.".format(results)

            flattened_results = flatten_results_dict(results)
            for k, v in flattened_results.items():
                try:
                    v = float(v)
                except Exception as e:
                    raise ValueError(
                        "[EvalHook] eval_function should return a nested dict of float. "
                        "Got '{}: {}' instead.".format(k, v)
                    ) from e
            runner.storage.put_scalars(**flattened_results, smoothing_hint=False)

        # Evaluation may take different time among workers.
        # A barrier make them start the next iteration together.
        dist_comm.synchronize()


    def after_val_iter(self, runner):
        if not self.by_epoch:
            next_iter = self.runner.iter + 1
            if self._period > 0 and next_iter % self._period == 0:
                # do the last eval in after_train
                if next_iter != self.runner.max_iter:
                    self._do_eval(runner)

    def after_val_epoch(self, runner):
        if self.by_epoch:
            next_epoch = self.runner.epoch + 1
            if self._period > 0 and next_epoch % self._period == 0:
                # do the last eval in after_train
                if next_epoch != self.runner.max_epoch:
                    self._do_eval(runner)


    def after_run(self, runner):
        # This condition is to prevent the eval from running after a failed training
        if self.by_epoch:
            if self.runner.epoch + 1 >= self.trainer.max_epoch:
                self._do_eval(runner)
        else:
            if self.runner.iter + 1 >= self.runner.max_iter:
                self._do_eval(runner)
        # func is likely a closure that holds reference to the trainer
        # therefore we clean it to avoid circular reference in the end
        del self._func
