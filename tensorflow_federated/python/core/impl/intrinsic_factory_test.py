# Lint as: python3
# Copyright 2018, The TensorFlow Federated Authors.
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

from absl.testing import absltest

from tensorflow_federated.python.core.api import intrinsics
from tensorflow_federated.python.core.api import placements


class FederatedSecureSumTest(absltest.TestCase):

  def test_type_signature_with_int(self):
    value = intrinsics.federated_value(1, placements.CLIENTS)
    bitwidth = 8

    intrinsic = intrinsics.federated_secure_sum(value, bitwidth)

    self.assertEqual(intrinsic.type_signature.compact_representation(),
                     'int32@SERVER')

  def test_type_signature_with_structure_of_ints(self):
    value = intrinsics.federated_value([1, [1, 1]], placements.CLIENTS)
    bitwidth = [8, [4, 2]]

    intrinsic = intrinsics.federated_secure_sum(value, bitwidth)

    self.assertEqual(intrinsic.type_signature.compact_representation(),
                     '<int32,<int32,int32>>@SERVER')

  def test_raises_type_error_with_value_float(self):
    value = intrinsics.federated_value(1.0, placements.CLIENTS)
    bitwidth = intrinsics.federated_value(1, placements.SERVER)

    with self.assertRaises(TypeError):
      intrinsics.federated_secure_sum(value, bitwidth)

  def test_raises_type_error_with_bitwith_int_at_server(self):
    value = intrinsics.federated_value(1, placements.CLIENTS)
    bitwidth = intrinsics.federated_value(1, placements.SERVER)

    with self.assertRaises(TypeError):
      intrinsics.federated_secure_sum(value, bitwidth)

  def test_raises_type_error_with_different_structures(self):
    value = intrinsics.federated_value([1, [1, 1]], placements.CLIENTS)
    bitwidth = 8

    with self.assertRaises(TypeError):
      intrinsics.federated_secure_sum(value, bitwidth)


if __name__ == '__main__':
  absltest.main()
