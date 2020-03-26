# Lint as: python3
# Copyright 2019, The TensorFlow Federated Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for shared training loops."""

import collections
import os

from absl import flags
import numpy as np
import tensorflow as tf
import tensorflow_federated as tff

from tensorflow_federated.python.research.utils import adapters
from tensorflow_federated.python.research.utils import checkpoint_manager
from tensorflow_federated.python.research.utils import training_loop

_Batch = collections.namedtuple('Batch', ['x', 'y'])

FLAGS = flags.FLAGS


def _from_tff_result(state):
  return tff.learning.framework.ServerState(
      model=tff.learning.ModelWeights(
          list(state.model.trainable), list(state.model.non_trainable)),
      optimizer_state=list(state.optimizer_state),
      delta_aggregate_state=[],
      model_broadcast_state=[])


class BasicAdapter(adapters.IterativeProcessPythonAdapter):
  """Converts iterative process results from anonymous tuples."""

  def __init__(self, iterative_process):
    self._iterative_process = iterative_process

  def initialize(self):
    initial_state = self._iterative_process.initialize()
    return _from_tff_result(initial_state)

  def next(self, state, data):
    state, metrics = self._iterative_process.next(state, data)
    state = _from_tff_result(state)
    metrics = metrics._asdict(recursive=True)
    outputs = None
    return adapters.IterationResult(state, metrics, outputs)


def _build_federated_averaging_process():
  iterative_process = tff.learning.build_federated_averaging_process(
      _uncompiled_model_fn,
      client_optimizer_fn=tf.keras.optimizers.SGD,
      server_optimizer_fn=tf.keras.optimizers.SGD)
  return BasicAdapter(iterative_process)


def _uncompiled_model_fn():
  keras_model = tff.simulation.models.mnist.create_keras_model(
      compile_model=False)
  input_spec = _create_input_spec()
  return tff.learning.from_keras_model(
      keras_model=keras_model,
      input_spec=input_spec,
      loss=tf.keras.losses.SparseCategoricalCrossentropy())


def _batch_fn():
  batch = _Batch(
      x=np.ones([1, 784], dtype=np.float32), y=np.ones([1, 1], dtype=np.int64))
  return batch


def _create_input_spec():
  return _Batch(
      x=tf.TensorSpec(shape=[None, 784], dtype=tf.float32),
      y=tf.TensorSpec(dtype=tf.int64, shape=[None, 1]))


class ExperimentRunnerTest(tf.test.TestCase):

  def test_raises_non_iterative_process(self):
    FLAGS.total_rounds = 10
    FLAGS.experiment_name = 'non_iterative_process'
    bad_iterative_process = _build_federated_averaging_process().next
    federated_data = [[_batch_fn()]]

    def client_datasets_fn(round_num):
      del round_num
      return federated_data

    def evaluate_fn(state):
      del state
      return {}

    temp_filepath = self.get_temp_dir()
    FLAGS.root_output_dir = temp_filepath
    with self.assertRaises(TypeError):
      training_loop.run([bad_iterative_process], client_datasets_fn,
                        evaluate_fn)

  def test_raises_non_callable_client_dataset(self):
    FLAGS.total_rounds = 10
    FLAGS.experiment_name = 'non_callable_client_dataset'
    iterative_process = _build_federated_averaging_process()
    federated_data = [[_batch_fn()]]

    client_dataset = federated_data

    def evaluate_fn(state):
      del state
      return {}

    temp_filepath = self.get_temp_dir()
    FLAGS.root_output_dir = temp_filepath
    with self.assertRaises(TypeError):
      training_loop.run(iterative_process, client_dataset, evaluate_fn)

  def test_raises_non_callable_evaluate_fn(self):
    FLAGS.total_rounds = 10
    FLAGS.experiment_name = 'non_callable_evaluate'
    iterative_process = _build_federated_averaging_process()
    federated_data = [[_batch_fn()]]

    def client_datasets_fn(round_num):
      del round_num
      return federated_data

    metrics_dict = {}

    temp_filepath = self.get_temp_dir()
    FLAGS.root_output_dir = temp_filepath
    with self.assertRaises(TypeError):
      training_loop.run(iterative_process, client_datasets_fn, metrics_dict)

  def test_raises_non_str_output_dir(self):
    FLAGS.total_rounds = 10
    FLAGS.root_output_dir = 1
    FLAGS.experiment_name = 'non_str_output_dir'
    iterative_process = _build_federated_averaging_process()
    federated_data = [[_batch_fn()]]

    def client_datasets_fn(round_num):
      del round_num
      return federated_data

    def eval_fn(state):
      del state
      return {}

    with self.assertRaises(TypeError):
      training_loop.run(iterative_process, client_datasets_fn, eval_fn)

  def test_fedavg_training_decreases_loss(self):
    FLAGS.total_rounds = 1
    FLAGS.experiment_name = 'fedavg_decreases_loss'
    batch = _batch_fn()
    federated_data = [[batch]]
    iterative_process = _build_federated_averaging_process()

    def client_datasets_fn(round_num):
      del round_num
      return federated_data

    def evaluate(state):
      keras_model = tff.simulation.models.mnist.create_keras_model(
          compile_model=True)
      state.model.assign_weights_to(keras_model)
      return {'loss': keras_model.evaluate(batch.x, batch.y)}

    initial_state = iterative_process.initialize()

    temp_filepath = self.get_temp_dir()
    FLAGS.root_output_dir = temp_filepath
    final_state = training_loop.run(iterative_process, client_datasets_fn,
                                    evaluate)
    self.assertLess(
        evaluate(final_state)['loss'],
        evaluate(initial_state)['loss'])

  def test_checkpoint_manager_saves_state(self):
    FLAGS.total_rounds = 1
    FLAGS.experiment_name = 'checkpoint_manager_saves_state'
    iterative_process = _build_federated_averaging_process()
    federated_data = [[_batch_fn()]]

    def client_datasets_fn(round_num):
      del round_num
      return federated_data

    def evaluate_fn(state):
      del state
      return {}

    temp_filepath = self.get_temp_dir()
    FLAGS.root_output_dir = temp_filepath
    final_state = training_loop.run(iterative_process, client_datasets_fn,
                                    evaluate_fn)

    ckpt_manager = checkpoint_manager.FileCheckpointManager(
        os.path.join(
            temp_filepath,
            'checkpoints',
            FLAGS.experiment_name,
        ))
    restored_state, restored_round = ckpt_manager.load_latest_checkpoint(
        final_state)

    self.assertEqual(restored_round, 0)

    keras_model = tff.simulation.models.mnist.create_keras_model(
        compile_model=True)
    restored_state.model.assign_weights_to(keras_model)
    restored_loss = keras_model.test_on_batch(federated_data[0][0].x,
                                              federated_data[0][0].y)
    final_state.model.assign_weights_to(keras_model)
    final_loss = keras_model.test_on_batch(federated_data[0][0].x,
                                           federated_data[0][0].y)
    self.assertEqual(final_loss, restored_loss)


if __name__ == '__main__':
  tf.compat.v1.enable_v2_behavior()
  tf.test.main()
