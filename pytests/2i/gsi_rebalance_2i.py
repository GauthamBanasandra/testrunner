from base_2i import BaseSecondaryIndexingTests, log
from membase.api.rest_client import RestConnection, RestHelper
import random
import threading
from lib import testconstants
from lib.couchbase_helper.query_definitions import SQLDefinitionGenerator, RANGE_SCAN_TEMPLATE, QueryDefinition
from lib.membase.api.exception import CBQError, BucketFlushFailed
from lib.remote.remote_util import RemoteMachineShellConnection
from pytests.query_tests_helper import QueryHelperTests


class SecondaryIndexingRebalanceTests(BaseSecondaryIndexingTests, QueryHelperTests):
    def setUp(self):
        super(SecondaryIndexingRebalanceTests, self).setUp()
        self.rest = RestConnection(self.servers[0])
        self.n1ql_server = self.get_nodes_from_services_map(service_type="n1ql", get_all_nodes=False)
        self.create_primary_index = False
        self.restServer = self.get_nodes_from_services_map(service_type="index")
        self.rest = RestConnection(self.restServer)
        shell = RemoteMachineShellConnection(self.servers[0])
        info = shell.extract_remote_info().type.lower()
        if info == 'linux':
            self.cli_command_location = testconstants.LINUX_COUCHBASE_BIN_PATH
        elif info == 'windows':
            self.cmd_ext = ".exe"
            self.cli_command_location = testconstants.WIN_COUCHBASE_BIN_PATH_RAW
        elif info == 'mac':
            self.cli_command_location = testconstants.MAC_COUCHBASE_BIN_PATH
        else:
            raise Exception("OS not supported.")

    def tearDown(self):
        super(SecondaryIndexingRebalanceTests, self).tearDown()

    def test_gsi_rebalance_out_indexer_node(self):
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        nodes_out_list = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        # rebalance out a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [], [nodes_out_list])
        self.run_operation(phase="during")
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        self.sleep(30)
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance, [],
                                                      [nodes_out_list])
        self.run_operation(phase="after")

    def test_gsi_rebalance_in_indexer_node(self):
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        # rebalance in a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [self.servers[self.nodes_init]], [])
        self.run_operation(phase="during")
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        self.sleep(30)
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        # validate the results
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance,
                                                      [self.servers[self.nodes_init]], [])
        self.run_operation(phase="after")

    def test_gsi_rebalance_swap_rebalance(self):
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        nodes_out_list = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        to_add_nodes = [self.servers[self.nodes_init]]
        to_remove_nodes = [nodes_out_list]
        services_in = ["index"]
        log.info(self.servers[:self.nodes_init])
        # do a swap rebalance
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], to_add_nodes, [], services=services_in)
        self.run_operation(phase="during")
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init + 1], [], to_remove_nodes)
        self.run_async_index_operations(operation_type="query")
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        self.sleep(30)
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        # validate the results
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance,
                                                      to_add_nodes, to_remove_nodes, swap_rebalance=True)
        self.run_operation(phase="after")

    def test_cbindex_move_after_rebalance_in(self):
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        indexes, no_of_indexes = self._get_indexes_in_move_index_format(map_before_rebalance)
        log.info(indexes)
        to_add_nodes = [self.servers[self.nodes_init]]
        services_in = ["index"]
        index_server = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], to_add_nodes, [], services=services_in)
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        self._cbindex_move(index_server, self.servers[self.nodes_init], indexes)
        self.wait_for_cbindex_move_to_complete(self.servers[self.nodes_init], no_of_indexes)
        self.run_operation(phase="during")
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        # validate the results
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance,
                                                      to_add_nodes, [], swap_rebalance=True)
        self.run_operation(phase="after")

    def test_cbindex_move_with_mutations_and_query(self):
        index_server = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        indexes, no_of_indexes = self._get_indexes_in_move_index_format(map_before_rebalance)
        log.info(indexes)
        to_add_nodes = [self.servers[self.nodes_init]]
        services_in = ["index"]
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], to_add_nodes, [], services=services_in)
        rebalance.result()
        self._cbindex_move(index_server, self.servers[self.nodes_init], indexes)
        self.run_operation(phase="during")
        tasks = self.async_run_doc_ops()
        for task in tasks:
            task.result()
        self.wait_for_cbindex_move_to_complete(self.servers[self.nodes_init], no_of_indexes)
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        # validate the results
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance,
                                                      to_add_nodes, [], swap_rebalance=True)
        self.run_operation(phase="after")

    def test_create_index_when_gsi_rebalance_in_progress(self):
        index_server = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        self.run_operation(phase="before")
        self.sleep(30)
        services_in = ["index"]
        # rebalance in a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [self.servers[self.nodes_init]], [],
                                                 services=services_in)
        rebalance.result()
        # rebalance out a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [], [index_server])
        self.sleep(2)
        try:
            # when rebalance is in progress, run create index
            index_name_prefix = "random_index_" + str(random.randint(100000, 999999))
            self.n1ql_helper.run_cbq_query(
                query="CREATE INDEX " + index_name_prefix + " ON default(age) USING GSI  WITH {'defer_build': True};",
                server=self.n1ql_node)
        except Exception, ex:
            log.info(str(ex))
            if "Indexer Cannot Process Create Index - Rebalance In Progress" not in str(ex):
                self.fail("index creation did not fail with expected error : {0}".format(str(ex)))
        else:
            self.fail("index creation did not fail as expected")
        self.run_operation(phase="during")
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()

    # rerun once MB-22886 is fixed
    def test_drop_index_when_gsi_rebalance_in_progress(self):
        index_server = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        self.run_operation(phase="before")
        self.sleep(30)
        services_in = ["index"]
        # rebalance in a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [self.servers[self.nodes_init]], [],
                                                 services=services_in)
        rebalance.result()
        # rebalance out a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [], [index_server])
        self.sleep(2)
        try:
            # when rebalance is in progress, run drop index
            self._drop_index(self.query_definitions[0], self.buckets[0])
        except Exception, ex:
            log.info(str(ex))
            if "Indexer Cannot Process Create Index - Rebalance In Progress" not in str(ex):
                self.fail("index creation did not fail with expected error : {0}".format(str(ex)))
        else:
            self.fail("drop index did not fail as expected")
        self.run_operation(phase="during")
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()

    def test_bucket_delete_and_flush_when_gsi_rebalance_in_progress(self):
        index_server = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        services_in = ["index"]
        # rebalance in a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [self.servers[self.nodes_init]], [],
                                                 services=services_in)
        rebalance.result()
        # rebalance out a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [], [index_server])
        self.sleep(2)
        # try deleting and flushing bucket during gsi rebalance
        status1 = self.rest.delete_bucket(bucket=self.buckets[0])
        if status1:
            self.fail("deleting bucket succeeded during gsi rebalance")
        try:
            status2 = self.rest.flush_bucket(bucket=self.buckets[0])
        except Exception, ex:
            if "unable to flush bucket" not in str(ex):
                    self.fail("flushing bucket failed with unexpected error message")
        self.run_operation(phase="during")
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        # validate the results
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance,
                                                      [self.servers[self.nodes_init]], [index_server],
                                                      swap_rebalance=True)
        self.run_operation(phase="after")

    def test_gsi_rebalance_works_when_querying_is_in_progress(self):
        index_server = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        services_in = ["index"]
        # rebalance in a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [self.servers[self.nodes_init]], [],
                                                 services=services_in)
        rebalance.result()
        # start querying
        t1 = threading.Thread(target=self.run_async_index_operations, args=("query",))
        t1.start()
        # rebalance out a indexer node when querying is in progress
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [], [index_server])
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        t1.join()
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        # validate the results
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance,
                                                      [self.servers[self.nodes_init]], [index_server],
                                                      swap_rebalance=True)
        self.run_operation(phase="after")

    def test_gsi_rebalance_works_when_mutations_are_in_progress(self):
        index_server = self.get_nodes_from_services_map(service_type="index", get_all_nodes=False)
        self.run_operation(phase="before")
        self.sleep(30)
        map_before_rebalance, stats_map_before_rebalance = self._return_maps()
        services_in = ["index"]
        # rebalance in a node
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [self.servers[self.nodes_init]], [],
                                                 services=services_in)
        rebalance.result()
        # start kv mutations
        results = []
        tasks = self.async_run_doc_ops()
        for task in tasks:
            results.append(threading.Thread(target=task.result()))
        for result in results:
            result.start()
        # rebalance out a indexer node when kv mutations are in progress
        rebalance = self.cluster.async_rebalance(self.servers[:self.nodes_init], [], [index_server])
        reached = RestHelper(self.rest).rebalance_reached()
        self.assertTrue(reached, "rebalance failed, stuck or did not complete")
        rebalance.result()
        for result in results:
            result.join()
        map_after_rebalance, stats_map_after_rebalance = self._return_maps()
        # validate the results
        self.n1ql_helper.verify_indexes_redistributed(map_before_rebalance, map_after_rebalance,
                                                      stats_map_before_rebalance, stats_map_after_rebalance,
                                                      [self.servers[self.nodes_init]], [index_server],
                                                      swap_rebalance=True)
        self.run_operation(phase="after")

    def _return_maps(self):
        index_map = self.get_index_map()
        stats_map = self.get_index_stats(perNode=False)
        return index_map, stats_map

    def _cbindex_move(self, src_node, dst_node, index_list, username="Administrator", password="password",
                      expect_failure=False):
        ip_address = str(dst_node).replace("ip:", "").replace(" port", "").replace(" ssh_username:root", "")
        cmd = """cbindex -type move -indexes '{0}' -with '{{"dest":"{1}"}}' -auth '{2}:{3}'""".format(index_list,
                                                                                                      ip_address,
                                                                                                      username,
                                                                                                      password)
        log.info(cmd)
        remote_client = RemoteMachineShellConnection(src_node)
        command = "{0}/{1}".format(self.cli_command_location, cmd)
        output, error = remote_client.execute_command(command)
        remote_client.log_command_output(output, error)
        if error:
            if expect_failure:
                log.info("cbindex move failed")
                return output, error
            else:
                self.fail("cbindex move failed")
        else:
            log.info("cbindex move started successfully : {0}".format(output))
        return output, error

    def _get_indexes_in_move_index_format(self, index_map):
        bucket_index_array = []
        for bucket in index_map:
            for index in index_map[bucket]:
                bucket_index_array.append(bucket + ":" + index)
        bucket_index_string = ",".join(bucket_index_array[:len(bucket_index_array) / 2])
        return bucket_index_string, len(bucket_index_array) / 2

    def wait_for_cbindex_move_to_complete(self, dst_node, count):
        no_of_indexes_moved = 0
        exit_count = 0
        while no_of_indexes_moved != count and exit_count != 10:
            index_map = self.get_index_map()
            host_names_after_rebalance = []
            index_distribution_map_after_rebalance = {}
            for bucket in index_map:
                for index in index_map[bucket]:
                    host_names_after_rebalance.append(index_map[bucket][index]['hosts'])
            for node in host_names_after_rebalance:
                index_distribution_map_after_rebalance[node] = index_distribution_map_after_rebalance.get(node, 0) + 1
            ip_address = str(dst_node).replace("ip:", "").replace(" port", "").replace(" ssh_username:root", "")
            log.info(ip_address)
            log.info(index_distribution_map_after_rebalance)
            if ip_address in index_distribution_map_after_rebalance:
                no_of_indexes_moved = index_distribution_map_after_rebalance[ip_address]
            else:
                no_of_indexes_moved = 0
            log.info("waiting for cbindex move to complete")
            self.sleep(30)
            exit_count += 1
        if no_of_indexes_moved == count:
            log.info("cbindex move completed")
        else:
            self.fail("timed out waiting for cbindex move to complete")

    def run_operation(self, phase="before"):
        if phase == "before":
            self.run_async_index_operations(operation_type="create_index")
        elif phase == "during":
            self.run_async_index_operations(operation_type="query")
        else:
            self.run_async_index_operations(operation_type="query")
            self.run_async_index_operations(operation_type="drop_index")

    def _drop_index(self, query_definition, bucket):
        try:
            query = query_definition.generate_index_drop_query(
                bucket=bucket,
                use_gsi_for_secondary=self.use_gsi_for_secondary,
                use_gsi_for_primary=self.use_gsi_for_primary)
            log.info(query)
            actual_result = self.n1ql_helper.run_cbq_query(query=query,
                                                           server=self.n1ql_server)
        except Exception, ex:
            log.info(ex)
            query = "select * from system:indexes"
            actual_result = self.n1ql_helper.run_cbq_query(query=query,
                                                           server=self.n1ql_server)
            log.info(actual_result)
        finally:
            return actual_result