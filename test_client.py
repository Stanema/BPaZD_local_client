"""Contract checks using isolated sibling servers; no existing database is touched."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from main import ClientHandler, ThreadingHTTPServer, exchange


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent.parent / 'BPaZD_local_server' / 'main.py'
        if not path.exists():
            raise unittest.SkipTest('Sibling local server is unavailable')
        spec = importlib.util.spec_from_file_location('lab', path)
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
        cls.server = lab.LabServer(('127.0.0.1', 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:{}'.format(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_local_roundtrip_and_error(self):
        self.assertEqual(exchange(self.base, 'GET', 'Patient')['data']['resourceType'], 'Bundle')
        created = exchange(self.base, 'POST', 'Patient', body={
            'resourceType': 'Patient', 'name': [{'family': 'Client-Test'}]})
        self.assertEqual(created['status'], 201)
        self.assertTrue(created['headers']['Location'])
        patient_id = created['data']['id']
        self.assertEqual(exchange(self.base, 'GET', 'Patient', patient_id)['data'], created['data'])
        observation = {'resourceType': 'Observation', 'status': 'final',
                       'subject': {'reference': 'Patient/' + patient_id},
                       'code': {'coding': [{'system': 'http://loinc.org', 'code': '8867-4'}]},
                       'valueQuantity': {'value': 74, 'unit': 'beats/minute',
                                         'system': 'http://unitsofmeasure.org', 'code': '/min'}}
        self.assertEqual(exchange(self.base, 'POST', 'Observation', body=observation)['status'], 201)
        error = exchange(self.base, 'GET', 'Patient', 'missing')
        self.assertEqual(error['status'], 404)
        self.assertEqual(error['data']['resourceType'], 'OperationOutcome')

    def test_validation(self):
        for args in [dict(base='file:///tmp/test', method='GET', kind='Patient'),
                     dict(base=self.base, method='PUT', kind='Patient'),
                     dict(base=self.base, method='POST', kind='Patient',
                          body={'resourceType': 'Patient', 'id': 'x'})]:
            with self.assertRaises(ValueError):
                exchange(**args)

    def test_browser_proxy_and_origin_protection(self):
        with ThreadingHTTPServer(('127.0.0.1', 0), ClientHandler) as ui:
            thread = threading.Thread(target=ui.serve_forever, daemon=True)
            thread.start()
            try:
                url = 'http://127.0.0.1:{}'.format(ui.server_port)
                self.assertIn(b'BPaZD FHIR client', urlopen(url).read())
                payload = json.dumps(dict(base=self.base, method='GET', kind='Patient', resource_id='')).encode()
                request = Request(url + '/api/request', data=payload,
                                  headers={'Content-Type': 'application/json'})
                self.assertEqual(json.load(urlopen(request))['status'], 200)
                request.add_header('Origin', 'https://untrusted.example')
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request)
                self.assertEqual(caught.exception.code, 403)
            finally:
                ui.shutdown()
                thread.join()

    def test_full_server_crud(self):
        try:
            from f7pbkbpd import create_app
            from werkzeug.serving import make_server
        except ImportError:
            self.skipTest('Full server and its Flask dependencies are not on PYTHONPATH')
        with tempfile.TemporaryDirectory() as temp:
            app = create_app({'TESTING': True, 'DATABASE': str(Path(temp) / 'test.sqlite')})
            server = make_server('127.0.0.1', 0, app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:{}'.format(server.server_port)
            try:
                body = {'resourceType': 'Patient', 'name': [{'family': 'Client-Test'}]}
                result = exchange(base, 'POST', 'Patient', body=body)
                self.assertEqual(result['status'], 201)
                rid = result['data']['id']
                body['name'][0]['family'] = 'Updated-Test'
                self.assertEqual(exchange(base, 'PUT', 'Patient', rid, body)['status'], 200)
                self.assertEqual(exchange(base, 'GET', 'Patient', rid)['data']['name'], body['name'])
                deleted = exchange(base, 'DELETE', 'Patient', rid)
                self.assertEqual(deleted['status'], 204)
                self.assertEqual(deleted['text'], '')
                self.assertEqual(exchange(base, 'GET', 'Patient', rid)['status'], 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
