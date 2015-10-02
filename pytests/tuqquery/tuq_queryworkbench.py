import time
from TestInput import TestInputSingleton
from basetestcase import BaseTestCase
from couchbase_helper.documentgenerator import BlobGenerator
from membase.api.rest_client import RestConnection
from tuq import QueryTests


class QueryWorkbenchTests(BaseTestCase):
    n1ql_port =8094
    _input = TestInputSingleton.input
    num_items = _input.param("items", 100)
    _value_size = _input.param("value_size", 256)
    gen_create = BlobGenerator('loadOne', 'loadOne',_value_size, end=num_items)
    #bucket and ram quota
    buckets_ram = {
        "CUSTOMER": 100,
        "DISTRICT": 100,
        "HISTORY": 100,
        "ITEM": 100,
        "NEW_ORDER": 100,
        "ORDERS": 100,
        "ORDER_LINE": 100,
        }

    def setUp(self):
        super(QueryWorkbenchTests, self).setUp()
        server = self.master
        if self.input.tuq_client and "client" in self.input.tuq_client:
            server = self.tuq_client
        self.rest = RestConnection(server)
        # drop and recreate buckets
        for i, bucket_name in enumerate(self.buckets_ram.keys()):
            self.rest.create_bucket(bucket=bucket_name,
                                   ramQuotaMB=int(self.buckets_ram[bucket_name]),
                                   replicaNumber=0,
                                   proxyPort=11218+i)
        time.sleep(60)
        self._async_load_all_buckets(self.master, self.gen_create, "create", 0)



    def tearDown(self):
        super(QueryWorkbenchTests, self).tearDown()



    def test_describe(self):
        for bucket_name in self.rest.get_buckets():
            query = "describe %s" % bucket_name
            print query
            result = self.rest.query_tool(query, self.n1ql_port,describe=True)
            print result
