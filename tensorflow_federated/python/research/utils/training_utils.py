# Lint as: python3
# Copyright 2020, The TensorFlow Federated Authors.
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
"""Shared library for setting up federated training experiments."""

import collections

from absl import logging
import numpy as np
import tensorflow as tf


# TODO(b/143440780): Create more comprehensive tuple conversion by adding an
# explicit namedtuple checking utility.
def convert_to_tuple_dataset(dataset):
  """Converts a dataset to one where elements have a tuple structure.

  Args:
    dataset: A `tf.data.Dataset` where elements either have a mapping
      structure of format {"x": <features>, "y": <labels>}, or a tuple-like
        structure of format (<features>, <labels>).

  Returns:
    A `tf.data.Dataset` object where elements are tuples of the form
    (<features>, <labels>).

  """
  example_structure = dataset.element_spec
  if isinstance(example_structure, collections.Mapping):
    # We assume the mapping has `x` and `y` keys.
    convert_map_to_tuple = lambda example: (example['x'], example['y'])
    try:
      return dataset.map(convert_map_to_tuple)
    except:
      raise ValueError('For datasets with a mapping structure, elements must '
                       'have format {"x": <features>, "y": <labels>}.')
  elif isinstance(example_structure, tuple):

    if hasattr(example_structure, '_fields') and isinstance(
        example_structure._fields, collections.Sequence) and all(
            isinstance(f, str) for f in example_structure._fields):
      # Dataset has namedtuple structure
      convert_tuplelike_to_tuple = lambda x: (x[0], x[1])
    else:
      # Dataset does not have namedtuple structure
      convert_tuplelike_to_tuple = lambda x, y: (x, y)

    try:
      return dataset.map(convert_tuplelike_to_tuple)
    except:
      raise ValueError('For datasets with tuple-like structure, elements must '
                       'have format (<features>, <labels>).')
  else:
    raise ValueError(
        'Expected evaluation dataset to have elements with a mapping or '
        'tuple-like structure, found {} instead.'.format(example_structure))


def build_evaluate_fn(eval_dataset, model_builder, loss_builder,
                      metrics_builder, assign_weights_to_keras_model):
  """Builds an evaluation function for a given model and test dataset.

  The evaluation function takes as input a fed_avg_schedule.ServerState, and
  computes metrics on a keras model with the same weights.

  Args:
    eval_dataset: A `tf.data.Dataset` object. Dataset elements should either
      have a mapping structure of format {"x": <features>, "y": <labels>}, or a
        tuple structure of format (<features>, <labels>).
    model_builder: A no-arg function that returns a `tf.keras.Model` object.
    loss_builder: A no-arg function returning a `tf.keras.losses.Loss` object.
    metrics_builder: A no-arg function that returns a list of
      `tf.keras.metrics.Metric` objects.
    assign_weights_to_keras_model: A function taking arguments
      (state, keras_model) that assigns the weights of state to the keras_model.

  Returns:
    A function that take as input the state of an iterative process and returns
    a dict of (name, value) pairs for each associated evaluation metric.
  """

  def compiled_eval_keras_model():
    model = model_builder()
    model.compile(
        loss=loss_builder(),
        optimizer=tf.keras.optimizers.SGD(),  # Dummy optimizer for evaluation
        metrics=metrics_builder())
    return model

  eval_tuple_dataset = convert_to_tuple_dataset(eval_dataset)

  def evaluate_fn(state):
    """Evaluation function to be used during training."""
    keras_model = compiled_eval_keras_model()
    assign_weights_to_keras_model(state, keras_model)
    logging.info('Evaluating the current model')
    eval_metrics = keras_model.evaluate(eval_tuple_dataset, verbose=0)
    return dict(zip(keras_model.metrics_names, eval_metrics))

  return evaluate_fn


def build_client_datasets_fn(train_dataset, train_clients_per_round):
  """Builds the function for generating client datasets at each round.

  Args:
    train_dataset: A `tff.simulation.ClientData` object.
    train_clients_per_round: The number of client participants in each round.

  Returns:
    A function which returns a list of `tff.simulation.ClientData` objects at a
    given round round_num.
  """

  def client_datasets(round_num):
    del round_num  # Unused.
    sampled_clients = np.random.choice(
        train_dataset.client_ids, size=train_clients_per_round, replace=False)
    return [
        train_dataset.create_tf_dataset_for_client(client)
        for client in sampled_clients
    ]

  return client_datasets
