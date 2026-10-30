"""Relay native Computer Use consent to a capable client; never decide it here."""
import json
from .errors import BridgeError

COMPUTER_INTEGRATIONS={'plugins.computer-use@openai-bundled','plugins.unified-computer-use@openai-bundled'}


class ApplicationApprovals:
    def _application_approval_policy(self):
        integrations=json.loads(self.project_policy['integrations']) if self.project_policy else []
        if not callable(self.native_approval_handler) or not COMPUTER_INTEGRATIONS.intersection(integrations):return 'never'
        return {'granular':{'sandbox_approval':False,'rules':False,'mcp_elicitations':True,'request_permissions':False,'skill_approval':False}}

    def _relay_application_approval(self,params,generation):
        if self._application_approval_policy()=='never':raise BridgeError('NATIVE_CLIENT_REQUIRED','No native consent client is connected.')
        worker,project=self._worker(params.get('threadId'))
        if worker['role'].lower()=='coordinator' or project['id']!=self.project_scope:
            raise BridgeError('PROJECT_ACCESS_DENIED','Only this connection managed workers may request native app consent.')
        if params.get('serverName') not in ('node_repl','cua_repl'):
            raise BridgeError('NATIVE_APPROVAL_UNSUPPORTED','Only the supported native UI SDK servers may request app consent.')
        if params.get('mode')!='form' or params.get('requestedSchema')!={'type':'object','properties':{}}:
            raise BridgeError('NATIVE_APPROVAL_UNSUPPORTED','Only a native Computer Use form request may be relayed.')
        meta=params.get('_meta')
        if not isinstance(meta,dict) or meta.get('connector_id')!='computer-use' or meta.get('connector_name')!='Computer Use' or meta.get('codex_approval_kind')!='mcp_tool_call':
            raise BridgeError('NATIVE_APPROVAL_UNSUPPORTED','Other connector and security requests are not relayed.')
        app=meta.get('tool_params',{}).get('app') if isinstance(meta.get('tool_params'),dict) else None
        if not isinstance(app,str) or not app.strip() or app=='computer-audio':
            raise BridgeError('NATIVE_APPROVAL_UNSUPPORTED','An exact native application is required; audio approval is excluded.')
        display=meta.get('tool_params_display');message=params.get('message')
        if meta['tool_params']!={'app':app} or not isinstance(display,list) or len(display)!=1 or not isinstance(display[0],dict) or display[0].get('name')!='app' or display[0].get('display_name')!='App' or not isinstance(display[0].get('value'),str):
            raise BridgeError('NATIVE_APPROVAL_UNSUPPORTED','Only the actual single-application consent shape is supported.')
        if not isinstance(message,str) or len(message)>1024 or '\n' in message or not message.startswith(('Allow Codex to use ','Allow Computer Use to use ')) or not message.endswith('?') or display[0]['value'] not in message:
            raise BridgeError('NATIVE_APPROVAL_UNSUPPORTED','Unsupported native application-consent prompt.')
        if meta.get('persist') not in (['session'],['session','always']) or meta.get('riskLevel') not in ('low','medium','high'):
            raise BridgeError('NATIVE_APPROVAL_UNSUPPORTED','Unsupported native consent persistence/risk shape.')
        rpc=self._transport
        if not rpc or rpc.generation!=generation:raise BridgeError('NATIVE_APPROVAL_EXPIRED','The original native transport was replaced.')
        identity=(params['threadId'],params.get('turnId'))
        deliveries=self.registry.rows("SELECT turn_id,stage FROM messages WHERE thread_id=? AND owner_token=? AND state IN ('preparing','sent','unknown')",(params['threadId'],self.instance))
        if not any(row['turn_id']==identity[1] or (row['turn_id'] is None and row['stage']=='dispatching') for row in deliveries):
            raise BridgeError('NATIVE_APPROVAL_EXPIRED','No exact owned delivery is awaiting this native request.')
        with rpc.guard:
            if identity not in rpc.active:raise BridgeError('NATIVE_APPROVAL_EXPIRED','The original worker turn is no longer executing.')
        # Forward the actual native form and metadata, never a worker-written
        # ordinary question and never a fabricated acceptance or persisted grant.
        request={key:params[key] for key in ('mode','message','requestedSchema','_meta') if key in params}
        def valid():
            try:self._worker(params['threadId'])
            except BridgeError:return False
            rows=self.registry.rows("SELECT turn_id,stage FROM messages WHERE thread_id=? AND owner_token=? AND state IN ('preparing','sent','unknown')",(params['threadId'],self.instance))
            if not any(row['turn_id']==identity[1] or (row['turn_id'] is None and row['stage']=='dispatching') for row in rows):return False
            with rpc.guard:return self._transport is rpc and not rpc.closed and identity in rpc.active and any(value is params for value in rpc.elicitations.values())
        if not valid():raise BridgeError('NATIVE_APPROVAL_EXPIRED','The original app request expired before relay.')
        result=self.native_approval_handler(request,valid)
        if not valid():raise BridgeError('NATIVE_APPROVAL_EXPIRED','The native request or grant ended while its client was waiting.')
        if not isinstance(result,dict) or result.get('action') not in ('accept','decline','cancel'):
            raise BridgeError('NATIVE_APPROVAL_INVALID','The native client returned no valid consent response.')
        return {key:result[key] for key in ('action','content','_meta') if key in result}
