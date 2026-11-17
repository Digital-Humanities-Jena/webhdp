"""OpenAPI 3.1 description of the stable public Link data and OAuth contract."""


def document(base):
    ref = lambda name: {'$ref': '#/components/schemas/' + name}
    param = lambda name: {'name': name, 'in': 'path', 'required': True, 'schema': {'type': 'string'}}
    response = lambda schema, description='Success': {'description': description, 'content': {'application/json': {'schema': schema}}}
    errors = {str(code): {'description': 'Problem Details; OAuth endpoints additionally return error and error_description.', 'content': {'application/problem+json': {'schema': ref('Problem')}}} for code in (400, 401, 403, 404, 409, 413, 429, 500)}
    def operation(summary, schema, *, scope=None, code=200, request=None, parameters=None):
        result = {'summary': summary, 'responses': {str(code): response(schema), **errors}, 'security': [{'linkBearer': []}] if scope else []}
        if scope:
            result['description'] = 'Required bearer scope: ' + scope
        if request:
            result['requestBody'] = request
        if parameters:
            result['parameters'] = parameters
        return result
    def json_body(schema):
        return {'required': True, 'content': {'application/json': {'schema': schema}}}
    def form_body(schema):
        return {'required': True, 'content': {'application/x-www-form-urlencoded': {'schema': schema}}}
    obj = {'type': 'object'}
    paths = {
        '/discovery': {'get': operation('Discover the instance, authorization flow and supported features', obj)},
        '/openapi.json': {'get': operation('Read this OpenAPI contract', obj)},
        '/oauth/request': {'get': operation('Validate an authorization request for the WebHDP consent screen', obj, parameters=[{'name': name, 'in': 'query', 'required': name != 'scope', 'schema': {'type': 'string'}} for name in ('client_id', 'redirect_uri', 'response_type', 'code_challenge', 'code_challenge_method', 'state', 'scope')])},
        '/oauth/authorize': {'post': operation('Approve or deny consent with the existing WebHDP user JWT', obj, request=json_body(ref('AuthorizationRequest')))},
        '/oauth/token': {'post': operation('Exchange a one-use authorization code using S256 PKCE', ref('TokenResponse'), request=form_body({'type': 'object', 'required': ['grant_type', 'code', 'client_id', 'redirect_uri', 'code_verifier'], 'properties': {key: {'type': 'string'} for key in ('grant_type', 'code', 'client_id', 'redirect_uri', 'code_verifier')}}))},
        '/oauth/revoke': {'post': operation('Revoke a bearer token', obj, request=form_body({'type': 'object', 'required': ['token'], 'properties': {'token': {'type': 'string'}}}))},
        '/pipelines': {'get': operation('List explicitly granted pipeline publications', {'type': 'object', 'properties': {'pipelines': {'type': 'array', 'items': ref('Pipeline')}}}, scope='pipelines:read')},
        '/pipelines/{pipeline_id}': {'get': operation('Read a pinned pipeline, graph and scalar parameter JSON Schema', ref('Pipeline'), scope='pipelines:read', parameters=[param('pipeline_id')])},
        '/uploads': {'post': operation('Upload one bounded input file; archives are never automatically extracted', ref('Upload'), scope='uploads:write', code=201, request={'required': True, 'content': {'multipart/form-data': {'schema': {'type': 'object', 'required': ['file'], 'properties': {'file': {'type': 'string', 'format': 'binary'}}}}}})},
        '/uploads/{upload_id}': {'delete': operation('Delete an upload not used by an active run', obj, scope='uploads:write', code=204, parameters=[param('upload_id')])},
        '/runs': {'get': operation('List at most 100 most recent runs owned by this application and user', {'type': 'object', 'properties': {'runs': {'type': 'array', 'items': ref('Run')}}}, scope='runs:read'),
                  'post': operation('Accept a durable idempotent run', ref('Run'), scope='runs:write', code=202, parameters=[{'name': 'Idempotency-Key', 'in': 'header', 'required': True, 'schema': {'type': 'string', 'minLength': 16, 'maxLength': 80}}], request=json_body({'type': 'object', 'additionalProperties': False, 'required': ['pipeline_id', 'inputs'], 'properties': {'pipeline_id': {'type': 'string'}, 'inputs': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': {'type': 'string', 'format': 'uuid'}}, 'parameters': {'type': 'object'}}}))},
        '/runs/{run_id}': {'get': operation('Poll durable status, step progress and artifact metadata', ref('Run'), scope='runs:read', parameters=[param('run_id')])},
        '/runs/{run_id}/cancel': {'post': operation('Cancel queued work or request cancellation between components', ref('Run'), scope='runs:write', parameters=[param('run_id')])},
        '/runs/{run_id}/artifacts/{artifact_id}': {'get': operation('Download an owned artifact as an attachment', {'type': 'string', 'format': 'binary'}, scope='artifacts:read', parameters=[param('run_id'), param('artifact_id')])},
        '/grants': {'get': operation('List the signed-in WebHDP user’s connected application grants', obj)},
        '/grants/{token_id}': {'delete': operation('Revoke the signed-in WebHDP user’s grant', obj, code=204, parameters=[param('token_id')])},
    }
    for resource in ('clients', 'publications'):
        paths['/admin/' + resource] = {'get': operation('Administrator: list ' + resource, obj), 'post': operation('Administrator: create ' + resource, obj, code=201, request=json_body(obj))}
        paths['/admin/' + resource + '/{id}'] = {'patch': operation('Administrator: update ' + resource, obj, request=json_body(obj), parameters=[param('id')])}
    paths['/admin/pipeline-options'] = {'get': operation('Administrator: inspect native published versions and parameter options', obj)}
    paths['/admin/clients/{client_id}/tokens'] = {'post': operation('Administrator: issue a scoped service token once (server use only)', ref('TokenResponse'), code=201, parameters=[param('client_id')], request=json_body({'type': 'object', 'properties': {'user_id': {'type': 'integer'}, 'scope': {'type': 'string'}, 'expires_in': {'type': 'integer', 'minimum': 60, 'maximum': 2592000}}}))}
    paths['/admin/tokens'] = {'get': operation('Administrator: inspect token metadata without raw secrets', obj)}
    paths['/admin/tokens/{token_id}'] = {'delete': operation('Administrator: revoke a token', obj, code=204, parameters=[param('token_id')])}
    paths['/admin/runs'] = {'get': operation('Administrator: inspect the central queue', obj)}
    paths['/admin/runs/{run_id}/cancel'] = {'post': operation('Administrator: cancel a run', ref('Run'), parameters=[param('run_id')])}
    for path, operations in paths.items():
        if path.startswith('/admin/') or path.startswith('/grants') or path == '/oauth/authorize':
            for op in operations.values():
                op['security'] = [{'webhdpSession': []}]
    paths['/runs/{run_id}/artifacts/{artifact_id}']['get']['responses']['200'] = {'description': 'Artifact bytes; SHA-256 ETag, attachment disposition and range requests supported.', 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}
    doc = {'openapi': '3.1.0', 'jsonSchemaDialect': 'https://json-schema.org/draft/2020-12/schema',
            'info': {'title': 'WebHDP-Link API', 'version': '1.0.0', 'description': 'Pipeline execution through a central WebHDP instance. OAuth code + S256 PKCE for browsers; administrator-issued scoped bearer tokens for service backends. Only explicitly published immutable contracts are exposed.'},
            'servers': [{'url': base.rstrip('/') + '/api/v1/link'}], 'paths': paths,
            'components': {'securitySchemes': {'linkBearer': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'opaque WebHDP-Link access token'}, 'webhdpSession': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'WebHDP JWT'}},
                           'schemas': {
                               'Problem': {'type': 'object', 'required': ['type', 'title', 'status', 'detail', 'code'], 'properties': {'type': {'type': 'string'}, 'title': {'type': 'string'}, 'status': {'type': 'integer'}, 'detail': {'type': 'string'}, 'code': {'type': 'string'}, 'instance': {'type': 'string'}, 'error': {'type': 'string'}, 'error_description': {'type': 'string'}}},
                               'AuthorizationRequest': {'type': 'object', 'required': ['client_id', 'redirect_uri', 'response_type', 'code_challenge', 'code_challenge_method', 'state', 'approve'], 'properties': {**{key: {'type': 'string'} for key in ('client_id', 'redirect_uri', 'response_type', 'code_challenge', 'code_challenge_method', 'state', 'scope')}, 'approve': {'type': 'boolean'}}},
                               'TokenResponse': {'type': 'object', 'required': ['access_token', 'token_type', 'expires_in', 'scope', 'issuer'], 'properties': {'access_token': {'type': 'string'}, 'token_type': {'const': 'Bearer'}, 'expires_in': {'type': 'integer'}, 'scope': {'type': 'string'}, 'issuer': {'type': 'string'}, 'token_id': {'type': 'string'}}},
                               'Upload': {'type': 'object', 'required': ['id', 'name', 'size', 'sha256', 'media_type'], 'properties': {'id': {'type': 'string', 'format': 'uuid'}, 'name': {'type': 'string'}, 'size': {'type': 'integer'}, 'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}, 'media_type': {'type': 'string'}}},
                               'Pipeline': {'type': 'object', 'required': ['id', 'name', 'pipeline_version', 'input', 'parameter_schema', 'structure'], 'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'}, 'description': {'type': 'string'}, 'pipeline_identifier': {'type': 'string'}, 'pipeline_version': {'type': 'string'}, 'input': {'type': 'object'}, 'execution_mode': {'enum': ['record', 'bundle']}, 'parameter_schema': {'type': 'object'}, 'structure': {'type': 'array', 'items': {'type': 'object'}}}},
                               'Run': {'type': 'object', 'required': ['id', 'pipeline_id', 'pipeline_version', 'status', 'progress', 'artifacts'], 'properties': {'id': {'type': 'string', 'format': 'uuid'}, 'pipeline_id': {'type': 'string'}, 'pipeline_version': {'type': 'string'}, 'status': {'enum': ['queued', 'running', 'succeeded', 'failed', 'cancelled']}, 'cancel_requested': {'type': 'boolean'}, 'progress': {'type': 'object', 'properties': {'completed': {'type': 'integer'}, 'total': {'type': 'integer'}}}, 'steps': {'type': 'array', 'items': {'type': 'object'}}, 'artifacts': {'type': 'array', 'items': {'allOf': [ref('Upload'), {'type': 'object', 'properties': {'download_url': {'type': 'string'}}}]}}, 'error': {'type': ['object', 'null']}, 'created_at': {'type': 'string', 'format': 'date-time'}, 'completed_at': {'type': ['string', 'null'], 'format': 'date-time'}}},
                           }}}

    schemas = doc['components']['schemas']
    string = {'type': 'string'}
    timestamp = {'type': 'string', 'format': 'date-time'}
    nullable_time = {'type': ['string', 'null'], 'format': 'date-time'}
    def model(properties, required=(), *, additional=False):
        return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': additional}
    def array(schema):
        return {'type': 'array', 'items': schema}
    def integer(lo, hi):
        return {'type': 'integer', 'minimum': lo, 'maximum': hi}
    schemas['InputContract'] = model({'min_files': integer(1,1000), 'max_files': integer(1,1000),
                                     'extensions': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'type': 'string', 'pattern': r'^\.[a-z0-9]{1,12}$'}}}, ['min_files','max_files','extensions'])
    scalar = {'type': ['string','number','boolean','null']}
    schemas['ScalarParameter'] = model({'type': {'enum': ['string','integer','number','boolean']}, 'title': string, 'description': string,
        'default': scalar, 'enum': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': scalar},
        'minimum': {'type': 'number'}, 'maximum': {'type': 'number'}, 'minLength': integer(0,10000), 'maxLength': integer(0,10000)}, ['type'])
    schemas['ParameterMapping'] = model({**schemas['ScalarParameter']['properties'], 'step_id': string, 'parameter': string, 'label': string}, ['step_id','parameter'])
    schemas['ParameterSchema'] = model({'$schema': {'const':'https://json-schema.org/draft/2020-12/schema'}, 'type': {'const':'object'},
        'properties': {'type':'object','additionalProperties':ref('ScalarParameter')}, 'additionalProperties': {'const':False}}, ['$schema','type','properties','additionalProperties'])
    schemas['PipelineStep'] = model({'id': string, 'name': string, 'component': string, 'version': string}, ['id','name','component','version'])
    schemas['HpcPolicy'] = model({'enabled': {'type':'boolean','default':False}, 'retain_allocation': {'type':'boolean','default':False,
        'description':'Retain a running job-owned allocation only when explicitly enabled. Retained allocations require administrator management unless both publications explicitly enable same-user reuse.'},
        'reuse_retained_allocation': {'type':'boolean','default':False,'description':'Requires retain_allocation. Serially reuse an idle retained Link allocation for the same user and identical resource policy, without extending or resetting its expiry.'},
        'walltime_hours': {**integer(1,168),'description':'If omitted, use the central HPC configuration duration.'}, 'partition': string, 'gpu_count': {**integer(0,8),'default':1}, 'gpu_type': string})
    client_properties = {'id': {'type':'string','pattern':r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$'}, 'name': {'type':'string','minLength':1,'maxLength':160}, 'enabled': {'type':'boolean','default':True},
        'origins': {'type':'array','maxItems':50,'uniqueItems':True,'items':{'type':'string','format':'uri'}, 'description':'Exact HTTPS origins; loopback HTTP is allowed for development. No wildcard or path.'},
        'redirect_uris': {'type':'array','maxItems':50,'uniqueItems':True,'items':{'type':'string','format':'uri'}, 'description':'Exact redirect URI allowlist belonging to the registered origins. No fragment or OAuth response query parameters.'},
        'pipeline_ids': {'type':'array','maxItems':50,'uniqueItems':True,'items':string}, 'max_queued_runs': {**integer(1,10000),'default':20},
        'max_concurrent_runs': {**integer(1,64),'default':1}, 'max_upload_bytes': {**integer(1,20*1024**3),'default':100*1024**2},
        'max_storage_bytes': {**integer(1,1024**4),'default':1024**3}}
    schemas['ClientCreate'] = model(client_properties, ['name'])
    schemas['ClientPatch'] = model({k:v for k,v in client_properties.items() if k!='id'})
    schemas['Client'] = model({**client_properties,'created_at':timestamp}, ['id','name','enabled','origins','redirect_uris','pipeline_ids','max_queued_runs','max_concurrent_runs','max_upload_bytes','max_storage_bytes','created_at'])
    pub_properties = {'id': client_properties['id'], 'name': client_properties['name'], 'description': {'type':'string','maxLength':5000},
        'pipeline_identifier':string, 'pipeline_version':string, 'enabled':{'type':'boolean','default':True}, 'input':ref('InputContract'),
        'parameters':{'type':'object','maxProperties':64,'additionalProperties':ref('ParameterMapping')}, 'execution_mode':{'enum':['record','bundle'],'default':'record'},
        'step_timeout_seconds':{**integer(1,43200),'default':3600}, 'hpc':ref('HpcPolicy')}
    schemas['PublicationCreate'] = model(pub_properties, ['id','name','pipeline_identifier','pipeline_version','input'])
    schemas['PublicationPatch'] = model({k:v for k,v in pub_properties.items() if k in {'name','description','enabled'}})
    pipeline_properties = {k:v for k,v in pub_properties.items() if k not in {'parameters','hpc','step_timeout_seconds'}}
    pipeline_properties.update(parameter_schema=ref('ParameterSchema'),structure=array(ref('PipelineStep')))
    schemas['Pipeline'] = model(pipeline_properties, list(pipeline_properties))
    schemas['Publication'] = model({**pipeline_properties,'parameters':pub_properties['parameters'],'step_timeout_seconds':pub_properties['step_timeout_seconds'],'hpc':ref('HpcPolicy')}, list(pipeline_properties)+['parameters','step_timeout_seconds','hpc'])
    schemas['Progress'] = model({'completed':integer(0,1000000),'total':integer(0,1000000),
        'phase': {'type':'string','enum':['queued','waiting_for_resources','processing','finalizing','completed'],
            'description':'Optional execution phase derived from persisted state. queued: waiting for a worker; waiting_for_resources: worker accepted an HPC job but its owned allocation is not ready; processing: preparing or executing native components; finalizing: native execution or allocation ended and Link is settling results; completed: any terminal Link status. Run.status distinguishes success, failure and cancellation. No scheduler identifiers or cluster details are exposed.'}}, ['completed','total'])
    schemas['RunStep'] = model({'id':string,'name':string,'status':{'enum':['pending','running','completed','failed','skipped']}}, ['id','name','status'])
    schemas['Artifact'] = model({'id':{'type':'string','format':'uuid'},'name':string,'size':{'type':'integer','minimum':0},
        'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'media_type':string,'download_url':{'type':'string','format':'uri-reference'}}, ['id','name','size','sha256','media_type','download_url'])
    run_properties = {'id':{'type':'string','format':'uuid'},'pipeline_id':string,'pipeline_name':string,'pipeline_version':string,
        'status':{'enum':['queued','running','succeeded','failed','cancelled']},'progress_url':{'type':'string','format':'uri-reference'},'cancel_requested':{'type':'boolean'},
        'progress':ref('Progress'),'steps':array(ref('RunStep')),'artifacts':array(ref('Artifact')),
        'error':{'oneOf':[{'type':'null'},model({'code':string,'detail':string},['code','detail'])]},
        'created_at':timestamp,'started_at':nullable_time,'completed_at':nullable_time,'reused':{'type':'boolean'}}
    schemas['Run'] = model(run_properties,[key for key in run_properties if key!='reused'])
    schemas['Job'] = model({**run_properties,'client_id':string,'client_name':string},[key for key in run_properties if key!='reused']+['client_id','client_name'])
    schemas['AdminRun'] = model({**run_properties,'client_id':string,'user_id':{'type':'integer'},'hpc_cleanup_pending':{'type':'boolean'}},[key for key in run_properties if key!='reused']+['client_id','user_id','hpc_cleanup_pending'])
    token_properties = {'id':string,'client_id':string,'user_id':{'type':'integer'},'scope':string,'service':{'type':'boolean'},'created_at':timestamp,'expires_at':timestamp,'revoked':{'type':'boolean'}}
    schemas['TokenMetadata'] = model(token_properties,list(token_properties))
    schemas['Grant'] = model({**token_properties,'client_name':string},list(token_properties)+['client_name'])
    schemas['Upload']['properties']['created_at'] = timestamp
    schemas['Upload']['additionalProperties'] = False
    paths['/jobs'] = {'get':operation('List the signed-in user’s processing jobs across applications',model({'jobs':array(ref('Job'))},['jobs']))}
    paths['/jobs/{run_id}'] = {'get':operation('Read an owned job from a bookmark without an application token',ref('Job'),parameters=[param('run_id')])}
    paths['/jobs/{run_id}/cancel'] = {'post':operation('Cancel the signed-in user’s job',ref('Job'),parameters=[param('run_id')])}
    paths['/jobs/{run_id}/artifacts/{artifact_id}'] = {'get':operation('Download a job artifact using the WebHDP user session',{'type':'string','format':'binary'},parameters=[param('run_id'),param('artifact_id')])}
    paths['/jobs/{run_id}/artifacts/{artifact_id}']['get']['responses']['200'] = paths['/runs/{run_id}/artifacts/{artifact_id}']['get']['responses']['200']
    paths['/grants']['get']['responses']['200'] = response(model({'grants':array(ref('Grant'))},['grants']))
    for resource,name in (('clients','Client'),('publications','Publication')):
        paths['/admin/'+resource]['post']['requestBody'] = json_body(ref(name+'Create'))
        paths['/admin/'+resource]['post']['responses']['201'] = response(ref(name))
        paths['/admin/'+resource]['get']['responses']['200'] = response(model({resource:array(ref(name))},[resource]))
        paths['/admin/'+resource+'/{id}']['patch']['requestBody'] = json_body(ref(name+'Patch'))
        paths['/admin/'+resource+'/{id}']['patch']['responses']['200'] = response(ref(name))
    paths['/admin/runs']['get']['responses']['200'] = response(model({'runs':array(ref('AdminRun'))},['runs']))
    paths['/admin/runs/{run_id}/cancel']['post']['responses']['200'] = response(ref('AdminRun'))
    paths['/admin/tokens']['get']['responses']['200'] = response(model({'tokens':array(ref('TokenMetadata'))},['tokens']))
    schemas['ComponentParameterOption'] = model({'name':string,'type':{'enum':['string','number','integer','boolean']},'label':string,
        **{k:v for k,v in schemas['ScalarParameter']['properties'].items() if k not in {'type','title'}}},['name','type','label'])
    schemas['PipelineOptionStep'] = model({**schemas['PipelineStep']['properties'],'parameters':array(ref('ComponentParameterOption'))},['id','name','component','version','parameters'])
    schemas['PipelineOption'] = model({'identifier':string,'name':string,'versions':array(model({'version':string,'steps':array(ref('PipelineOptionStep'))},['version','steps']))},['identifier','name','versions'])
    paths['/admin/pipeline-options']['get']['responses']['200'] = response(model({'pipelines':array(ref('PipelineOption'))},['pipelines']))
    paths['/oauth/request']['get']['responses']['200'] = response(model({'client':model({'id':string,'name':string},['id','name']),
        'redirect_uri':string,'scope':string,'expires_in':{'type':'integer'},'pipelines':array(ref('Pipeline'))},['client','redirect_uri','scope','expires_in','pipelines']))
    paths['/oauth/authorize']['post']['responses']['200'] = response(model({'redirect_uri':{'type':'string','format':'uri'}},['redirect_uri']))
    paths['/oauth/revoke']['post']['responses']['200'] = {'description':'Token revoked, or token was already unknown/revoked. Empty response body.'}
    for path, operations in paths.items():
        for method, op in operations.items():
            if path.startswith('/jobs'):
                op['security'] = [{'webhdpSession':[]}]
            op['operationId'] = method + '_' + path.strip('/').replace('/','_').replace('{','').replace('}','').replace('.','_').replace('-','_')
            if '204' in op['responses']:
                op['responses']['204'] = {'description':'Completed; empty response body.'}
    return doc
