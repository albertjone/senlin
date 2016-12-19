# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

import mock
import six

from senlin.common import context
from senlin.common import exception as exc
from senlin.common.i18n import _
from senlin.db.sqlalchemy import api as db_api
from senlin.engine import cluster
from senlin.engine import node
from senlin.objects import cluster as co
from senlin.objects import node as no
from senlin.profiles import base as pb
from senlin.profiles.container import docker as docker_profile
from senlin.tests.unit.common import base
from senlin.tests.unit.common import utils


class TestContainerDockerProfile(base.SenlinTestCase):

    def setUp(self):
        super(TestContainerDockerProfile, self).setUp()

        self.context = utils.dummy_context()
        self.spec = {
            'type': 'container.dockerinc.docker',
            'version': '1.0',
            'properties': {
                'context': {
                    'region_name': 'RegionOne'
                },
                'name': 'docker_container',
                'image': 'hello-world',
                'command': '/bin/sleep 30',
                'port': 2375,
                'host_node': 'fake_node',
            }
        }

    def test_init(self):
        profile = docker_profile.DockerProfile('t', self.spec)
        self.assertIsNone(profile._dockerclient)
        self.assertIsNone(profile.container_id)
        self.assertIsNone(profile.host)

    @mock.patch.object(docker_profile.DockerProfile, 'do_validate')
    @mock.patch.object(db_api, 'node_add_dependents')
    @mock.patch.object(db_api, 'cluster_add_dependents')
    def test_create_with_host_node(self, mock_cadd, mock_nadd, mock_validate):
        mock_validate.return_value = None

        profile = docker_profile.DockerProfile.create(
            self.context, 'fake_name', self.spec)

        self.assertIsNotNone(profile)
        mock_nadd.assert_called_once_with(self.context, 'fake_node',
                                          profile.id, 'profile')
        self.assertEqual(0, mock_cadd.call_count)

    @mock.patch.object(docker_profile.DockerProfile, 'do_validate')
    @mock.patch.object(db_api, 'node_add_dependents')
    @mock.patch.object(db_api, 'cluster_add_dependents')
    def test_create_with_host_cluster(self, mock_cadd, mock_nadd,
                                      mock_validate):
        mock_validate.return_value = None
        spec = copy.deepcopy(self.spec)
        del spec['properties']['host_node']
        spec['properties']['host_cluster'] = 'fake_cluster'

        profile = docker_profile.DockerProfile.create(
            self.context, 'fake_name', spec)

        self.assertIsNotNone(profile)
        mock_cadd.assert_called_once_with(self.context, 'fake_cluster',
                                          profile.id)
        self.assertEqual(0, mock_nadd.call_count)

    @mock.patch.object(pb.Profile, 'delete')
    @mock.patch.object(pb.Profile, 'load')
    @mock.patch.object(db_api, 'node_remove_dependents')
    @mock.patch.object(db_api, 'cluster_remove_dependents')
    def test_delete_with_host_node(self, mock_cdel, mock_ndel, mock_load,
                                   mock_delete):
        profile = docker_profile.DockerProfile('t', self.spec)
        mock_load.return_value = profile

        res = docker_profile.DockerProfile.delete(self.context, 'FAKE_ID')

        self.assertIsNone(res)
        mock_load.assert_called_once_with(self.context, profile_id='FAKE_ID')
        mock_ndel.assert_called_once_with(self.context, 'fake_node',
                                          'FAKE_ID', 'profile')
        self.assertEqual(0, mock_cdel.call_count)
        mock_delete.assert_called_once_with(self.context, 'FAKE_ID')

    @mock.patch.object(pb.Profile, 'delete')
    @mock.patch.object(pb.Profile, 'load')
    @mock.patch.object(db_api, 'node_remove_dependents')
    @mock.patch.object(db_api, 'cluster_remove_dependents')
    def test_delete_with_host_cluster(self, mock_cdel, mock_ndel, mock_load,
                                      mock_delete):
        spec = copy.deepcopy(self.spec)
        del spec['properties']['host_node']
        spec['properties']['host_cluster'] = 'fake_cluster'
        profile = docker_profile.DockerProfile('fake_name', spec)
        mock_load.return_value = profile

        res = docker_profile.DockerProfile.delete(self.context, 'FAKE_ID')

        self.assertIsNone(res)
        mock_load.assert_called_once_with(self.context, profile_id='FAKE_ID')
        mock_cdel.assert_called_once_with(self.context, 'fake_cluster',
                                          'FAKE_ID')
        self.assertEqual(0, mock_ndel.call_count)

    @mock.patch('senlin.drivers.container.docker_v1.DockerClient')
    @mock.patch.object(docker_profile.DockerProfile, '_get_host_ip')
    @mock.patch.object(docker_profile.DockerProfile, '_get_host')
    @mock.patch.object(context, 'get_admin_context')
    def test_docker_client(self, mock_ctx, mock_host, mock_ip, mock_client):
        ctx = mock.Mock()
        mock_ctx.return_value = ctx
        profile = mock.Mock(type_name='os.nova.server')
        host = mock.Mock(rt={'profile': profile}, physical_id='server1')
        mock_host.return_value = host
        fake_ip = '1.2.3.4'
        mock_ip.return_value = fake_ip
        dockerclient = mock.Mock()
        mock_client.return_value = dockerclient
        profile = docker_profile.DockerProfile('container', self.spec)
        obj = mock.Mock()
        client = profile.docker(obj)
        self.assertEqual(dockerclient, client)
        mock_host.assert_called_once_with(ctx, 'fake_node', None)
        mock_ip.assert_called_once_with(obj, 'server1', 'os.nova.server')
        url = 'tcp://1.2.3.4:2375'
        mock_client.assert_called_once_with(url)

    @mock.patch.object(docker_profile.DockerProfile, '_get_host')
    def test_docker_client_wrong_host_type(self, mock_get):
        profile = mock.Mock(type_name='wrong_type')
        host = mock.Mock(rt={'profile': profile}, physical_id='server1')
        mock_get.return_value = host
        obj = mock.Mock()
        profile = docker_profile.DockerProfile('container', self.spec)
        ex = self.assertRaises(exc.InternalError,
                               profile.docker, obj)
        msg = _('Type of host node (wrong_type) is not supported')

        self.assertEqual(msg, ex.message)

    @mock.patch.object(docker_profile.DockerProfile, '_get_host_ip')
    @mock.patch.object(docker_profile.DockerProfile, '_get_host')
    def test_docker_client_get_host_ip_failed(self, mock_host, mock_ip):
        profile = mock.Mock(type_name='os.nova.server')
        host = mock.Mock(rt={'profile': profile}, physical_id='server1')
        mock_host.return_value = host
        mock_ip.return_value = None
        obj = mock.Mock()
        profile = docker_profile.DockerProfile('container', self.spec)
        ex = self.assertRaises(exc.InternalError,
                               profile.docker, obj)
        msg = _('Unable to determine the IP address of host node')

        self.assertEqual(msg, ex.message)

    @mock.patch.object(cluster.Cluster, 'load')
    def test_get_host_cluster(self, mock_load):
        cluster = mock.Mock()
        mock_load.return_value = cluster
        ctx = mock.Mock()
        profile = docker_profile.DockerProfile('container', self.spec)
        res = profile._get_host_cluster(ctx, 'host_cluster')
        self.assertEqual(cluster, res)
        mock_load.assert_called_once_with(ctx, cluster_id='host_cluster')

    @mock.patch.object(cluster.Cluster, 'load')
    def test_get_host_cluster_not_found(self, mock_load):
        mock_load.side_effect = exc.ResourceNotFound(type='cluster',
                                                     id='host_cluster')

        ctx = mock.Mock()
        profile = docker_profile.DockerProfile('container', self.spec)
        ex = self.assertRaises(exc.InternalError,
                               profile._get_host_cluster,
                               ctx, 'host_cluster')
        msg = _("The host cluster (host_cluster) could not be found.")

        self.assertEqual(msg, ex.message)

    @mock.patch.object(node.Node, 'load')
    def test__get_host_node_found(self, mock_load):
        node = mock.Mock()
        mock_load.return_value = node
        ctx = mock.Mock()
        profile = docker_profile.DockerProfile('container', self.spec)

        res = profile._get_host(ctx, 'host_node', None)

        self.assertEqual(node, res)
        mock_load.assert_called_once_with(ctx, node_id='host_node')

    @mock.patch.object(node.Node, 'load')
    def test__get_host_node_not_found(self, mock_load):
        mock_load.side_effect = exc.ResourceNotFound(type='node',
                                                     id='fake_node')
        profile = docker_profile.DockerProfile('container', self.spec)
        ctx = mock.Mock()

        ex = self.assertRaises(exc.InternalError,
                               profile._get_host,
                               ctx, 'fake_node', None)

        msg = _('The host node (fake_node) could not be found.')
        self.assertEqual(msg, ex.message)

    @mock.patch.object(docker_profile.DockerProfile, '_get_host_cluster')
    def test_get_random_node(self, mock_cluster):
        node1 = mock.Mock(status='ERROR')
        node2 = mock.Mock(status='ACTIVE')
        node3 = mock.Mock(status='ACTIVE')
        cluster = mock.Mock(rt={'nodes': [node1, node2, node3]})
        mock_cluster.return_value = cluster
        active_nodes = [node2, node3]
        profile = docker_profile.DockerProfile('container', self.spec)
        ctx = mock.Mock()
        node = profile._get_random_node(ctx, 'host_cluster')
        self.assertIn(node, active_nodes)

    @mock.patch.object(docker_profile.DockerProfile, '_get_host_cluster')
    def test_get_random_node_empty_cluster(self, mock_cluster):
        cluster = mock.Mock(rt={'nodes': []})
        mock_cluster.return_value = cluster
        profile = docker_profile.DockerProfile('container', self.spec)
        ctx = mock.Mock()
        ex = self.assertRaises(exc.InternalError,
                               profile._get_random_node,
                               ctx, 'host_cluster')
        msg = _('The cluster (host_cluster) contains no nodes')

        self.assertEqual(msg, ex.message)

    @mock.patch.object(docker_profile.DockerProfile, '_get_host_cluster')
    def test_get_random_node_no_active_nodes(self, mock_cluster):
        node1 = mock.Mock(status='ERROR')
        node2 = mock.Mock(status='ERROR')
        node3 = mock.Mock(status='ERROR')
        cluster = mock.Mock(rt={'nodes': [node1, node2, node3]})
        mock_cluster.return_value = cluster
        profile = docker_profile.DockerProfile('container', self.spec)
        ctx = mock.Mock()
        ex = self.assertRaises(exc.InternalError,
                               profile._get_random_node,
                               ctx, 'host_cluster')
        msg = _('There is no active nodes running in the cluster '
                '(host_cluster)')
        self.assertEqual(msg, ex.message)

    def test_get_host_ip_nova_server(self):
        addresses = {
            'private': [{'version': 4, 'OS-EXT-IPS:type': 'fixed',
                         'addr': '1.2.3.4'}]
        }
        server = mock.Mock(addresses=addresses)
        cc = mock.Mock()
        cc.server_get.return_value = server
        profile = docker_profile.DockerProfile('container', self.spec)
        profile._computeclient = cc
        obj = mock.Mock()
        host_ip = profile._get_host_ip(obj, 'fake_node', 'os.nova.server')
        self.assertEqual('1.2.3.4', host_ip)
        cc.server_get.assert_called_once_with('fake_node')

    def test_get_host_ip_heat_stack(self):
        oc = mock.Mock()
        stack = mock.Mock(
            outputs=[{'output_key': 'fixed_ip', 'output_value': '1.2.3.4'}]
        )
        oc.stack_get.return_value = stack
        profile = docker_profile.DockerProfile('container', self.spec)
        profile._orchestrationclient = oc
        obj = mock.Mock()

        host_ip = profile._get_host_ip(obj, 'fake_node', 'os.heat.stack')

        self.assertEqual('1.2.3.4', host_ip)
        oc.stack_get.assert_called_once_with('fake_node')

    def test_get_host_ip_heat_stack_no_outputs(self):
        oc = mock.Mock()
        stack = mock.Mock(outputs=None)
        oc.stack_get.return_value = stack
        profile = docker_profile.DockerProfile('container', self.spec)
        profile._orchestrationclient = oc
        obj = mock.Mock()

        ex = self.assertRaises(exc.InternalError,
                               profile._get_host_ip,
                               obj, 'fake_node', 'os.heat.stack')

        msg = _("Output 'fixed_ip' is missing from the provided stack node")

        self.assertEqual(msg, ex.message)

    def test_do_validate_with_cluster_and_node(self):
        spec = copy.deepcopy(self.spec)
        spec['properties']['host_cluster'] = 'fake_cluster'
        obj = mock.Mock()
        profile = docker_profile.DockerProfile('container', spec)

        ex = self.assertRaises(exc.InvalidSpec,
                               profile.do_validate, obj)

        self.assertEqual("Either 'host_cluster' or 'host_node' should be "
                         "specified, but not both.", six.text_type(ex))

    def test_do_validate_with_neither_cluster_or_node(self):
        spec = copy.deepcopy(self.spec)
        del spec['properties']['host_node']
        obj = mock.Mock()
        profile = docker_profile.DockerProfile('container', spec)

        ex = self.assertRaises(exc.InvalidSpec,
                               profile.do_validate, obj)

        self.assertEqual("Either 'host_cluster' or 'host_node' should be "
                         "specified.", six.text_type(ex))

    @mock.patch.object(no.Node, 'find')
    def test_do_validate_with_node(self, mock_find):
        obj = mock.Mock()
        profile = docker_profile.DockerProfile('container', self.spec)
        mock_find.return_value = mock.Mock()

        res = profile.do_validate(obj)

        self.assertIsNone(res)
        mock_find.assert_called_once_with(profile.context, 'fake_node')

    @mock.patch.object(no.Node, 'find')
    def test_do_validate_node_not_found(self, mock_find):
        obj = mock.Mock()
        profile = docker_profile.DockerProfile('container', self.spec)
        mock_find.side_effect = exc.ResourceNotFound(type='node',
                                                     id='fake_node')

        ex = self.assertRaises(exc.InvalidSpec,
                               profile.do_validate, obj)

        self.assertEqual("The specified host_node 'fake_node' could not be "
                         "found or is not unique.", six.text_type(ex))
        mock_find.assert_called_once_with(profile.context, 'fake_node')

    @mock.patch.object(co.Cluster, 'find')
    def test_do_validate_with_cluster(self, mock_find):
        spec = copy.deepcopy(self.spec)
        obj = mock.Mock()
        del spec['properties']['host_node']
        spec['properties']['host_cluster'] = 'fake_cluster'
        profile = docker_profile.DockerProfile('container', spec)
        mock_find.return_value = mock.Mock()

        res = profile.do_validate(obj)

        self.assertIsNone(res)
        mock_find.assert_called_once_with(profile.context, 'fake_cluster')

    @mock.patch.object(co.Cluster, 'find')
    def test_do_validate_cluster_not_found(self, mock_find):
        spec = copy.deepcopy(self.spec)
        del spec['properties']['host_node']
        spec['properties']['host_cluster'] = 'fake_cluster'
        obj = mock.Mock()
        mock_find.side_effect = exc.ResourceNotFound(type='node',
                                                     id='fake_cluster')
        profile = docker_profile.DockerProfile('container', spec)

        ex = self.assertRaises(exc.InvalidSpec,
                               profile.do_validate, obj)

        self.assertEqual("The specified host_cluster 'fake_cluster' could "
                         "not be found or is not unique.", six.text_type(ex))
        mock_find.assert_called_once_with(profile.context, 'fake_cluster')

    @mock.patch.object(db_api, 'node_add_dependents')
    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(docker_profile.DockerProfile, 'docker')
    def test_do_create(self, mock_docker, mock_ctx, mock_add):
        ctx = mock.Mock()
        mock_ctx.return_value = ctx
        dockerclient = mock.Mock()
        mock_docker.return_value = dockerclient
        container = {'Id': 'd' * 64}
        dockerclient.container_create.return_value = container
        container_id = 'd' * 36
        profile = docker_profile.DockerProfile('container', self.spec)
        host = mock.Mock(id='node_id')
        profile.host = host
        profile.cluster = cluster
        profile.id = 'profile_id'
        obj = mock.Mock(id='fake_con_id')
        ret_container_id = profile.do_create(obj)
        mock_add.assert_called_once_with(ctx, 'node_id', 'fake_con_id')
        self.assertEqual(container_id, ret_container_id)
        params = {
            'image': 'hello-world',
            'name': 'docker_container',
            'command': '/bin/sleep 30',
        }
        dockerclient.container_create.assert_called_once_with(**params)

    @mock.patch.object(docker_profile.DockerProfile, 'docker')
    def test_do_create_failed(self, mock_docker):
        mock_docker.side_effect = exc.InternalError
        profile = docker_profile.DockerProfile('container', self.spec)
        obj = mock.Mock()
        self.assertRaises(exc.EResourceCreation,
                          profile.do_create, obj)

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(db_api, 'node_remove_dependents')
    @mock.patch.object(docker_profile.DockerProfile, 'docker')
    def test_do_delete(self, mock_docker, mock_rem, mock_ctx):
        obj = mock.Mock(id='container1', physical_id='FAKE_PHYID')
        dockerclient = mock.Mock()
        ctx = mock.Mock()
        mock_ctx.return_value = ctx
        mock_docker.return_value = dockerclient
        host = mock.Mock(dependents={})
        host.id = 'node_id'
        profile = docker_profile.DockerProfile('container', self.spec)
        profile.host = host
        profile.id = 'profile_id'

        res = profile.do_delete(obj)

        self.assertIsNone(res)
        mock_rem.assert_called_once_with(ctx, 'node_id', 'container1')
        dockerclient.container_delete.assert_any_call('FAKE_PHYID')

    def test_do_delete_no_physical_id(self):
        obj = mock.Mock(physical_id=None)
        profile = docker_profile.DockerProfile('container', self.spec)
        self.assertIsNone(profile.do_delete(obj))

    @mock.patch.object(docker_profile.DockerProfile, 'docker')
    def test_do_delete_failed(self, mock_docker):
        obj = mock.Mock(physical_id='FAKE_ID')
        mock_docker.side_effect = exc.InternalError

        profile = docker_profile.DockerProfile('container', self.spec)

        self.assertRaises(exc.EResourceDeletion,
                          profile.do_delete, obj)
