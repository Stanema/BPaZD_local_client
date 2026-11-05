# BPaZD FHIR client

Run `main.py` in PyCharm, or `.venv/bin/python main.py`. Open
http://127.0.0.1:8090 if the browser does not open automatically.
Python 3.9+; no third-party packages required. Use `--no-browser` to suppress
browser launch or `--port 8091` to change the UI port. Stop with Ctrl+C.

Start the desired server separately. Select **BPaZD_local_server** (port 8080)
or **BPaZD_server** (port 5000), or enter a custom HTTP(S) server base URL
(e.g. `http://10.0.112.26:5000` when that course server is deployed and reachable).
The client appends `/fhir/Patient` or `/fhir/Observation` to this URL.

- **List resources** receives a Bundle and displays a readable table and raw JSON.
- **Select** loads a resource into the editor and fills its ID. **Read ID** fetches it again.
- **New example** fills a synthetic resource and clears the ID. For Observation,
  change `subject.reference` to an existing Patient ID on the selected server.
- **Create** sends POST; omit the body `id` and clear the Resource ID field.
- **Replace** sends PUT of the entire editor resource to the entered ID.
- **Delete** asks for confirmation, then deletes the entered resource ID.
  PUT and DELETE are disabled for the local-server preset, which lacks those methods.
- Import a single Patient/Observation JSON file into the editor; export saves the
  latest received response, including Bundles. Importing does not send anything.
- Response status, headers, raw JSON, and server validation errors appear below.
  After creation, select the returned row to read or edit the assigned ID.

These projects exchange a teaching subset of **HL7 FHIR JSON over HTTP**, not
HL7 v2 pipe-delimited messages or MLLP. The client sends user-initiated requests;
these servers do not provide push notifications. Reload a list to receive changes.
Use synthetic course data. This client adds no authentication or persistent storage.
HTTPS certificate verification is enabled; system HTTP proxies are bypassed.

The browser UI and request relay bind only to `127.0.0.1`. The relay checks Host
and Origin, does not follow redirects, and times out upstream requests after
15 seconds. Outgoing JSON is limited to 1 MiB; displayed responses to 8 MiB.
For Wireshark, capture loopback traffic on TCP port 8080 or 5000 (8090 is the UI).

Run `.venv/bin/python -m unittest -v` for local-server integration checks.
The sibling `BPaZD_local_server` must exist. Full-server CRUD checks also run
when `BPaZD_server` and its dependencies are available on `PYTHONPATH`; otherwise
that check is explicitly skipped. Tests use ephemeral ports, in-memory local-server
resources, and a temporary full-server database.
