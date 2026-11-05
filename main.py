"""Local browser client for the BPaZD teaching FHIR APIs (standard library only)."""
import argparse
import json
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_BODY = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exchange(base, method, kind, resource_id='', body=None):
    """Send one FHIR request; retain error bodies and HTTP metadata for display."""
    parts = urlsplit(base)
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError('Use an HTTP(S) server URL without credentials, query, or fragment.')
    if method not in ('GET', 'POST', 'PUT', 'DELETE') or kind not in ('Patient', 'Observation'):
        raise ValueError('Unsupported method or resource type.')
    resource_id = resource_id.strip()
    if method in ('PUT', 'DELETE') and not resource_id:
        raise ValueError('A resource ID is required.')
    if method == 'POST' and resource_id:
        raise ValueError('Clear the ID to create a resource.')
    payload = None
    if method in ('POST', 'PUT'):
        if not isinstance(body, dict) or body.get('resourceType') != kind:
            raise ValueError('JSON must be an object with the selected resourceType.')
        if method == 'POST' and 'id' in body:
            raise ValueError('Remove id before creating a resource.')
        if method == 'PUT' and 'id' in body and body['id'] != resource_id:
            raise ValueError('The body id must match the resource ID.')
        payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
        if len(payload) > MAX_BODY:
            raise ValueError('FHIR request exceeds 1 MiB.')
    url = base.rstrip('/') + '/fhir/' + kind
    if resource_id:
        url += '/' + quote(resource_id, safe='')
    request = Request(url, data=payload, method=method,
                      headers={'Accept': 'application/fhir+json',
                               'Content-Type': 'application/fhir+json'})
    # Direct connections make local traffic capture predictable; HTTPS uses default verification.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(8 * MAX_BODY + 1)
        if len(raw) > 8 * MAX_BODY:
            raise ValueError('Response exceeds the 8 MiB display limit.')
        text = raw.decode('utf-8', errors='replace')
        try:
            data = json.loads(text) if text else None
        except ValueError:
            data = None
        return {'status': response.code, 'reason': response.reason, 'url': url,
                'headers': dict(response.headers), 'text': text, 'data': data}


PAGE = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BPaZD FHIR client</title>
<style>
:root{font:16px system-ui;color:#17283b;background:#eef3f7}body{max-width:1200px;margin:30px auto;padding:0 20px}h1{margin-bottom:4px}p{color:#526477}section{background:white;padding:20px;border-radius:12px;margin:18px 0;box-shadow:0 2px 9px #16324f0b}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:end}label{display:flex;flex-direction:column;gap:6px;font-weight:600}input,select,button,textarea{font:inherit;border:1px solid #a9b9c9;border-radius:6px;padding:9px}input{min-width:180px}#base{width:320px}button{background:#17649c;color:white;cursor:pointer}button.secondary{background:#eef4f9;color:#174461}button:disabled{opacity:.5;cursor:wait}textarea{box-sizing:border-box;width:100%;height:300px;font:14px ui-monospace,monospace;margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:14px;max-height:480px;overflow:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #dce4ec;overflow-wrap:anywhere}td button{padding:4px 9px}#status{font-weight:600;white-space:pre-wrap}.error{color:#ad2525}.success{color:#176641}.scroll{overflow:auto}small{color:#526477}details{margin-top:16px}
</style>
<h1>BPaZD FHIR client</h1><p>Send, receive, and inspect HL7 FHIR Patient and Observation JSON.</p>
<section><div class="row">
<label>Server<select id="profile"><option value="8080">BPaZD_local_server · port 8080</option><option value="5000">BPaZD_server · port 5000</option><option value="custom">Custom server</option></select></label>
<label>Server base URL<input id="base" value="http://127.0.0.1:8080"></label>
<label>Resource<select id="kind"><option>Patient</option><option>Observation</option></select></label>
<label>Resource ID (blank lists all)<input id="rid" placeholder="synthetic-001"></label>
</div><p id="capabilities">Local server supports GET and POST. Data resets when it restarts.</p>
<div class="row"><button id="list">List resources</button><button id="read">Read ID</button><button class="secondary" id="example">New example</button></div></section>
<section><h2>Resource editor</h2><small>Load a JSON file, edit an example, or select a received resource. POST assigns a new ID; PUT replaces the selected ID.</small>
<textarea id="editor" aria-label="FHIR JSON resource" spellcheck="false"></textarea>
<div class="row"><button id="create">Create (POST)</button><button id="update">Replace (PUT)</button><button id="remove">Delete</button><button class="secondary" id="format">Format JSON</button><label>Import JSON<input type="file" id="file" accept=".json,application/json,application/fhir+json"></label></div></section>
<section aria-live="polite"><h2>Response</h2><div id="status">Ready.</div><p id="request"></p><div class="scroll"><table><thead><tr><th>ID</th><th>Name / observation</th><th>Details</th><th></th></tr></thead><tbody id="rows"></tbody></table></div>
<p><button class="secondary" id="export" disabled>Export response JSON</button></p><pre id="response">No response yet.</pre><details><summary>HTTP response headers</summary><pre id="headers"></pre></details></section>
<script>
const $=id=>document.getElementById(id);let last=null,busy=false;
function status(message,error=false){$('status').textContent=message;$('status').className=error?'error':'success'}
function capabilities(){const local=$('profile').value==='8080';$('update').disabled=busy||local;$('remove').disabled=busy||local;$('capabilities').textContent=local?'Local server supports GET and POST. Data resets when it restarts.':'BPaZD_server supports GET, POST, PUT, and DELETE. Custom servers must support these endpoints.'}
$('profile').onchange=()=>{if($('profile').value!=='custom')$('base').value='http://127.0.0.1:'+$('profile').value;capabilities()};$('base').oninput=()=>{$('profile').value='custom';capabilities()};
function example(){const kind=$('kind').value;const body=kind==='Patient'?{resourceType:'Patient',name:[{family:'Example-Demo',given:['Jana']}],gender:'female',birthDate:'2000-02-29'}:{resourceType:'Observation',status:'final',code:{coding:[{system:'http://loinc.org',code:'8867-4',display:'Heart rate'}]},subject:{reference:'Patient/synthetic-001'},valueQuantity:{value:74,unit:'beats/minute',system:'http://unitsofmeasure.org',code:'/min'}};$('rid').value='';$('editor').value=JSON.stringify(body,null,2)}
$('example').onclick=example;
function render(data){$('rows').replaceChildren();const resources=data?.resourceType==='Bundle'?(data.entry||[]).map(e=>e.resource):[data];for(const r of resources){if(!r||!['Patient','Observation'].includes(r.resourceType))continue;const tr=document.createElement('tr');const name=r.resourceType==='Patient'?(r.name||[]).map(n=>[...(n.given||[]),n.family].filter(Boolean).join(' ')).join('; '):(r.code?.text||r.code?.coding?.[0]?.display||r.code?.coding?.[0]?.code||'Observation');const detail=r.resourceType==='Patient'?[r.gender,r.birthDate].filter(Boolean).join(' · '):[r.subject?.reference,r.valueQuantity?`${r.valueQuantity.value} ${r.valueQuantity.unit||''}`:'',r.status].filter(Boolean).join(' · ');for(const value of [r.id||'',name,detail]){const td=document.createElement('td');td.textContent=value;tr.append(td)}const td=document.createElement('td'),b=document.createElement('button');b.textContent='Select';b.onclick=()=>{$('kind').value=r.resourceType;$('rid').value=r.id||'';$('editor').value=JSON.stringify(r,null,2)};td.append(b);tr.append(td);$('rows').append(tr)}}
async function send(method,list=false){if(busy)return;try{if(list)$('rid').value='';const id=$('rid').value.trim();if((method==='PUT'||method==='DELETE')&&!id)throw Error('Enter or select a resource ID first.');if(method==='DELETE'&&!confirm(`Delete ${$('kind').value}/${id} from ${$('base').value}?`))return;const body=['POST','PUT'].includes(method)?JSON.parse($('editor').value):null;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);status('Sending…');const response=await fetch('/api/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base:$('base').value.trim(),method,kind:$('kind').value,resource_id:id,body})});const result=await response.json();if(!response.ok)throw Error(result.error||'Client request failed');last=result;$('request').textContent=method+' '+result.url;$('response').textContent=result.data?JSON.stringify(result.data,null,2):(result.text||'(empty response)');$('headers').textContent=Object.entries(result.headers).map(([k,v])=>k+': '+v).join('\n');render(result.data);status(`HTTP ${result.status} ${result.reason}`,result.status>=400)}catch(e){status(e.message,true)}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);$('export').disabled=!last;capabilities()}}
$('list').onclick=()=>send('GET',true);$('read').onclick=()=>{$('rid').value.trim()?send('GET'):status('Enter or select an ID, or use List resources.',true)};$('create').onclick=()=>send('POST');$('update').onclick=()=>send('PUT');$('remove').onclick=()=>send('DELETE');
$('format').onclick=()=>{try{$('editor').value=JSON.stringify(JSON.parse($('editor').value),null,2)}catch(e){status(e.message,true)}};
$('file').onchange=async()=>{try{const f=$('file').files[0];if(!f)return;if(f.size>1048576)throw Error('File exceeds 1 MiB.');const data=JSON.parse(await f.text());if(!data||!['Patient','Observation'].includes(data.resourceType))throw Error('Import a single Patient or Observation resource.');$('kind').value=data.resourceType;$('rid').value=data.id||'';$('editor').value=JSON.stringify(data,null,2)}catch(e){status(e.message,true)}};
$('export').onclick=()=>{if(!last)return;const url=URL.createObjectURL(new Blob([last.data?JSON.stringify(last.data,null,2):last.text],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='fhir-response.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};example();capabilities();
</script></html>'''


class ClientHandler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        payload = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def trusted(self):
        expected = '127.0.0.1:{}'.format(self.server.server_port)
        return (self.headers.get('Host') == expected
                and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected
                and self.headers.get('Sec-Fetch-Site') not in ('cross-site',))

    def do_GET(self):
        if not self.trusted():
            self.reply(403, json.dumps({'error': 'Use the localhost client URL.'}))
        elif self.path == '/':
            self.reply(200, PAGE, 'text/html; charset=utf-8')
        else:
            self.reply(404, '{}')

    def do_POST(self):
        if not self.trusted():
            self.reply(403, json.dumps({'error': 'Cross-origin requests are forbidden.'}))
            return
        if self.path != '/api/request':
            self.reply(404, '{}')
            return
        self.connection.settimeout(20)
        try:
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Expected application/json.')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2 * MAX_BODY:
                raise ValueError('Invalid request size (limit 2 MiB).')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Incomplete request.')
            args = json.loads(raw)
            if not isinstance(args, dict):
                raise ValueError('Expected a request object.')
            for key in ('base', 'method', 'kind', 'resource_id'):
                if not isinstance(args.get(key), str):
                    raise ValueError('Missing or invalid ' + key)
            result = exchange(args['base'], args['method'], args['kind'],
                              args['resource_id'], args.get('body'))
            self.reply(200, json.dumps(result))
        except (ValueError, UnicodeError) as error:
            self.reply(400, json.dumps({'error': str(error)}))
        except (URLError, OSError, socket.timeout) as error:
            self.reply(502, json.dumps({'error': 'Connection failed: {}. Check the URL and start the server.'.format(error)}))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8090, help='Local client UI port (default: 8090)')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), ClientHandler)
    except OSError as error:
        parser.exit(1, 'Cannot start client: {}\n'.format(error))
    with server:
        url = 'http://127.0.0.1:{}'.format(server.server_port)
        print('BPaZD FHIR client: {} (Ctrl+C to stop)'.format(url), flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\nClient stopped.')


if __name__ == '__main__':
    main()
